using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Threading;
using Microsoft.Kinect;

namespace OpenClaw.KinectSdkAudioBridge
{
    internal static class Program
    {
        private const int SampleRate = 16000;
        private const int Channels = 1;
        private const int BitsPerSample = 16;

        private static volatile bool _stopRequested;
        private static DateTime _lastAngleLogUtc = DateTime.MinValue;

        private static int Main(string[] args)
        {
            var options = Options.Parse(args);
            if (options.ShowHelp)
            {
                Options.PrintHelp();
                return 0;
            }

            Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs eventArgs)
            {
                eventArgs.Cancel = true;
                _stopRequested = true;
            };

            var sensor = FindSensor();
            if (sensor == null)
            {
                Console.Error.WriteLine("No connected Kinect sensor found through Kinect SDK v1.8.");
                return 2;
            }

            try
            {
                sensor.Start();
                ConfigureAudio(sensor.AudioSource, options);

                sensor.AudioSource.BeamAngleChanged += OnBeamAngleChanged;
                sensor.AudioSource.SoundSourceAngleChanged += OnSoundSourceAngleChanged;

                using (var input = sensor.AudioSource.Start())
                using (var output = CreateOutput(options))
                {
                    Console.Error.WriteLine(
                        "Kinect SDK audio started: sensor={0}, beam_mode={1}, noise_suppression={2}, agc={3}",
                        sensor.UniqueKinectId,
                        sensor.AudioSource.BeamAngleMode,
                        sensor.AudioSource.NoiseSuppression,
                        sensor.AudioSource.AutomaticGainControlEnabled);

                    var started = DateTime.UtcNow;
                    var buffer = new byte[options.BufferBytes];
                    while (!_stopRequested)
                    {
                        if (options.ProbeSeconds > 0 &&
                            (DateTime.UtcNow - started).TotalSeconds >= options.ProbeSeconds)
                        {
                            break;
                        }

                        var read = input.Read(buffer, 0, buffer.Length);
                        if (read <= 0)
                        {
                            Thread.Sleep(5);
                            continue;
                        }

                        output.Write(buffer, 0, read);
                    }
                }

                sensor.AudioSource.Stop();
                sensor.Stop();
                Console.Error.WriteLine("Kinect SDK audio stopped.");
                return 0;
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("Kinect SDK audio failed: {0}", ex);
                try { sensor.Stop(); } catch { }
                return 1;
            }
        }

        private static KinectSensor FindSensor()
        {
            foreach (var sensor in KinectSensor.KinectSensors)
            {
                if (sensor.Status == KinectStatus.Connected)
                {
                    return sensor;
                }
            }

            return null;
        }

        private static void ConfigureAudio(KinectAudioSource audioSource, Options options)
        {
            audioSource.AutomaticGainControlEnabled = options.AutomaticGainControl;
            audioSource.NoiseSuppression = options.NoiseSuppression;
            audioSource.EchoCancellationMode = EchoCancellationMode.None;

            if (options.ManualBeamAngle.HasValue)
            {
                audioSource.BeamAngleMode = BeamAngleMode.Manual;
                audioSource.ManualBeamAngle = options.ManualBeamAngle.Value;
                return;
            }

            try
            {
                audioSource.BeamAngleMode = BeamAngleMode.Adaptive;
            }
            catch
            {
                audioSource.BeamAngleMode = BeamAngleMode.Automatic;
            }
        }

        private static Stream CreateOutput(Options options)
        {
            if (options.StdoutPcm)
            {
                return Console.OpenStandardOutput();
            }

            var path = options.WavPath;
            if (String.IsNullOrWhiteSpace(path))
            {
                Directory.CreateDirectory("data");
                path = Path.Combine("data", "kinect-sdk-probe.wav");
            }

            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path)) ?? ".");
            return new WaveFileWriter(path, SampleRate, Channels, BitsPerSample);
        }

        private static void OnBeamAngleChanged(object sender, BeamAngleChangedEventArgs eventArgs)
        {
            LogAngles(sender as KinectAudioSource, "beam", eventArgs.Angle, null);
        }

        private static void OnSoundSourceAngleChanged(object sender, SoundSourceAngleChangedEventArgs eventArgs)
        {
            LogAngles(sender as KinectAudioSource, "source", eventArgs.Angle, eventArgs.ConfidenceLevel);
        }

        private static void LogAngles(KinectAudioSource source, string kind, double angle, double? confidence)
        {
            var now = DateTime.UtcNow;
            if ((now - _lastAngleLogUtc).TotalMilliseconds < 250)
            {
                return;
            }

            _lastAngleLogUtc = now;
            var beam = source == null ? Double.NaN : source.BeamAngle;
            var sourceAngle = source == null ? Double.NaN : source.SoundSourceAngle;
            var sourceConfidence = source == null ? Double.NaN : source.SoundSourceAngleConfidence;
            Console.Error.WriteLine(
                "angle kind={0} changed={1} confidence={2} beam={3} source={4} source_confidence={5}",
                kind,
                angle.ToString("0.000", CultureInfo.InvariantCulture),
                confidence.HasValue ? confidence.Value.ToString("0.000", CultureInfo.InvariantCulture) : "-",
                beam.ToString("0.000", CultureInfo.InvariantCulture),
                sourceAngle.ToString("0.000", CultureInfo.InvariantCulture),
                sourceConfidence.ToString("0.000", CultureInfo.InvariantCulture));
        }

        private sealed class Options
        {
            public bool ShowHelp { get; private set; }
            public bool StdoutPcm { get; private set; }
            public string WavPath { get; private set; }
            public int ProbeSeconds { get; private set; }
            public int BufferBytes { get; private set; }
            public bool NoiseSuppression { get; private set; }
            public bool AutomaticGainControl { get; private set; }
            public double? ManualBeamAngle { get; private set; }

            private Options()
            {
                WavPath = Path.Combine("data", "kinect-sdk-probe.wav");
                ProbeSeconds = 10;
                BufferBytes = 3200;
                NoiseSuppression = true;
                AutomaticGainControl = false;
            }

            public static Options Parse(string[] args)
            {
                var options = new Options();
                var queue = new Queue<string>(args ?? new string[0]);
                while (queue.Count > 0)
                {
                    var arg = queue.Dequeue();
                    switch (arg)
                    {
                        case "--help":
                        case "-h":
                            options.ShowHelp = true;
                            break;
                        case "--stdout-pcm":
                            options.StdoutPcm = true;
                            break;
                        case "--wav":
                            options.WavPath = RequireValue(arg, queue);
                            break;
                        case "--probe-seconds":
                            options.ProbeSeconds = Int32.Parse(RequireValue(arg, queue), CultureInfo.InvariantCulture);
                            break;
                        case "--buffer-bytes":
                            options.BufferBytes = Int32.Parse(RequireValue(arg, queue), CultureInfo.InvariantCulture);
                            break;
                        case "--no-noise-suppression":
                            options.NoiseSuppression = false;
                            break;
                        case "--agc":
                            options.AutomaticGainControl = true;
                            break;
                        case "--manual-beam-angle":
                            options.ManualBeamAngle = Double.Parse(RequireValue(arg, queue), CultureInfo.InvariantCulture);
                            break;
                        default:
                            throw new ArgumentException("Unknown argument: " + arg);
                    }
                }

                return options;
            }

            public static void PrintHelp()
            {
                Console.WriteLine("OpenClaw Kinect SDK Audio Bridge");
                Console.WriteLine();
                Console.WriteLine("Options:");
                Console.WriteLine("  --wav <path>                  Write a 16 kHz mono PCM16 WAV probe file.");
                Console.WriteLine("  --stdout-pcm                  Write raw PCM16 to stdout instead of WAV.");
                Console.WriteLine("  --probe-seconds <seconds>     Capture duration. 0 means until Ctrl+C.");
                Console.WriteLine("  --manual-beam-angle <radians> Use a fixed beam angle instead of adaptive.");
                Console.WriteLine("  --agc                         Enable Kinect automatic gain control.");
                Console.WriteLine("  --no-noise-suppression        Disable Kinect noise suppression.");
            }

            private static string RequireValue(string arg, Queue<string> queue)
            {
                if (queue.Count == 0)
                {
                    throw new ArgumentException("Missing value for " + arg);
                }

                return queue.Dequeue();
            }
        }
    }

    internal sealed class WaveFileWriter : Stream
    {
        private readonly FileStream _file;
        private readonly int _sampleRate;
        private readonly short _channels;
        private readonly short _bitsPerSample;
        private long _dataBytes;

        public WaveFileWriter(string path, int sampleRate, int channels, int bitsPerSample)
        {
            _file = File.Create(path);
            _sampleRate = sampleRate;
            _channels = (short)channels;
            _bitsPerSample = (short)bitsPerSample;
            WriteHeader(0);
        }

        public override bool CanRead { get { return false; } }
        public override bool CanSeek { get { return false; } }
        public override bool CanWrite { get { return true; } }
        public override long Length { get { return _file.Length; } }
        public override long Position { get { return _file.Position; } set { throw new NotSupportedException(); } }

        public override void Flush()
        {
            _file.Flush();
        }

        public override int Read(byte[] buffer, int offset, int count)
        {
            throw new NotSupportedException();
        }

        public override long Seek(long offset, SeekOrigin origin)
        {
            throw new NotSupportedException();
        }

        public override void SetLength(long value)
        {
            throw new NotSupportedException();
        }

        public override void Write(byte[] buffer, int offset, int count)
        {
            _file.Write(buffer, offset, count);
            _dataBytes += count;
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _file.Seek(0, SeekOrigin.Begin);
                WriteHeader(_dataBytes);
                _file.Dispose();
            }

            base.Dispose(disposing);
        }

        private void WriteHeader(long dataBytes)
        {
            var byteRate = _sampleRate * _channels * _bitsPerSample / 8;
            var blockAlign = (short)(_channels * _bitsPerSample / 8);
            using (var writer = new BinaryWriter(_file, System.Text.Encoding.ASCII, true))
            {
                writer.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));
                writer.Write((int)(36 + dataBytes));
                writer.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"));
                writer.Write(System.Text.Encoding.ASCII.GetBytes("fmt "));
                writer.Write(16);
                writer.Write((short)1);
                writer.Write(_channels);
                writer.Write(_sampleRate);
                writer.Write(byteRate);
                writer.Write(blockAlign);
                writer.Write(_bitsPerSample);
                writer.Write(System.Text.Encoding.ASCII.GetBytes("data"));
                writer.Write((int)dataBytes);
            }
        }
    }
}

