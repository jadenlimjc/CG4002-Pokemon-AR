using System;
using System.Collections;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace CG4002.Comms
{
    // Attach this component to your own scene to use the transport without the debug canvas.
    public sealed class UnityComms : MonoBehaviour
    {
        public event Action<ReceivedMessage> MessageReceived;
        public SshMqttClient Client { get; private set; }
        public string Status => loadError ?? (paused ? "Paused" : Client?.Status ?? "Loading settings...");
        string loadError;
        bool paused, restartRequested = true;
        CancellationTokenSource lifetime;
        Task networkTask;

        IEnumerator Start()
        {
            string path = Path.Combine(Application.streamingAssetsPath, "secrets.json");
            string url = path.Contains("://") ? path : new Uri(path).AbsoluteUri;
            // StreamingAssets lives inside the APK on Android; it is not a normal file.
            using (var request = UnityWebRequest.Get(url))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                { loadError = "Cannot load secrets.json. Run root setup.sh before building."; yield break; }
                try
                {
                    var settings = JsonUtility.FromJson<ConnectionSecrets>(request.downloadHandler.text);
                    if (settings == null) throw new InvalidDataException("Empty connection settings.");
                    Client = new SshMqttClient(settings);
                }
                catch (Exception error) { loadError = "Settings: " + error.Message; }
            }
        }

        void Update()
        {
            if (networkTask != null && networkTask.IsCompleted)
            {
                if (networkTask.IsFaulted) loadError = "Connection stopped: " + networkTask.Exception.GetBaseException().Message;
                networkTask = null;
                lifetime.Dispose(); lifetime = null;
            }
            // Wait for the previous tunnel to close before starting a replacement.
            if (!paused && restartRequested && Client != null && networkTask == null)
            {
                restartRequested = false;
                lifetime = new CancellationTokenSource();
                var token = lifetime.Token;
                networkTask = Task.Run(() => Client.RunAsync(token));
            }
            if (Client == null) return;
            for (int i = 0; i < 256 && Client.TryDequeue(out var message); i++)
            {
                try { MessageReceived?.Invoke(message); }
                catch (Exception error) { Debug.LogException(error); }
            }
        }

        public void Reconnect()
        {
            if (Client == null) return; // Settings errors require fixing the file and restarting.
            loadError = null;
            restartRequested = true;
            lifetime?.Cancel();
        }

        void OnApplicationPause(bool value)
        {
            paused = value;
            if (value) lifetime?.Cancel();
            else restartRequested = true;
        }

        void OnDestroy()
        {
            lifetime?.Cancel();
            var source = lifetime;
            if (networkTask != null)
                _ = networkTask.ContinueWith(task => {
                    // Observe faults without invoking Unity APIs from a worker thread.
                    _ = task.Exception;
                    source?.Dispose();
                }, TaskScheduler.Default);
            else source?.Dispose();
        }
    }
}
