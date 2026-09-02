using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using UnityEngine;

public class NetworkManager : MonoBehaviour
{
    public static NetworkManager Instance { get; private set; }

    [Header("Connection Settings")]
    [SerializeField] private ConnectionMode mode = ConnectionMode.UDP;
    [SerializeField] private int listenPort = 8888;
    [SerializeField] private string serverIP = "192.168.1.100"; // Ultra96/laptop IP

    [Header("Status")]
    [SerializeField] private bool isConnected = false;
    [SerializeField] private string lastMessage = "";

    public bool IsConnected => isConnected;

    private UdpClient udpClient;
    private TcpClient tcpClient;
    private Thread receiveThread;
    private bool isRunning = false;
    private readonly object messageLock = new object();
    private string pendingMessage = null;

    public enum ConnectionMode
    {
        UDP,
        TCP_WebSocket
    }

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    private void Start()
    {
        StartListening();
    }

    private void Update()
    {
        // Process messages on main thread (Unity requires this for API calls)
        lock (messageLock)
        {
            if (pendingMessage != null)
            {
                ProcessMessage(pendingMessage);
                pendingMessage = null;
            }
        }
    }

    public void StartListening()
    {
        isRunning = true;

        if (mode == ConnectionMode.UDP)
        {
            receiveThread = new Thread(UDPReceiveLoop);
        }
        else
        {
            receiveThread = new Thread(TCPReceiveLoop);
        }

        receiveThread.IsBackground = true;
        receiveThread.Start();
        Debug.Log($"[Network] Listening on port {listenPort} ({mode})");
    }

    private void UDPReceiveLoop()
    {
        try
        {
            udpClient = new UdpClient(listenPort);
            IPEndPoint remoteEP = new IPEndPoint(IPAddress.Any, 0);
            isConnected = true;

            while (isRunning)
            {
                byte[] data = udpClient.Receive(ref remoteEP);
                string message = Encoding.UTF8.GetString(data);

                lock (messageLock)
                {
                    pendingMessage = message;
                    lastMessage = message;
                }
            }
        }
        catch (SocketException e)
        {
            if (isRunning)
                Debug.LogError($"[Network] UDP Error: {e.Message}");
        }
        finally
        {
            isConnected = false;
        }
    }

    private void TCPReceiveLoop()
    {
        try
        {
            TcpListener listener = new TcpListener(IPAddress.Any, listenPort);
            listener.Start();
            Debug.Log("[Network] TCP waiting for connection...");

            tcpClient = listener.AcceptTcpClient();
            isConnected = true;
            Debug.Log("[Network] TCP client connected");

            NetworkStream stream = tcpClient.GetStream();
            byte[] buffer = new byte[4096];

            while (isRunning)
            {
                int bytesRead = stream.Read(buffer, 0, buffer.Length);
                if (bytesRead == 0) break; // Client disconnected

                string message = Encoding.UTF8.GetString(buffer, 0, bytesRead);

                lock (messageLock)
                {
                    pendingMessage = message;
                    lastMessage = message;
                }
            }
        }
        catch (Exception e)
        {
            if (isRunning)
                Debug.LogError($"[Network] TCP Error: {e.Message}");
        }
        finally
        {
            isConnected = false;
        }
    }

    private void ProcessMessage(string jsonMessage)
    {
        try
        {
            GesturePayload payload = JsonUtility.FromJson<GesturePayload>(jsonMessage);
            GestureAction action = payload.GetGestureAction();

            if (action == GestureAction.NONE)
            {
                Debug.LogWarning($"[Network] Unknown gesture: {jsonMessage}");
                return;
            }

            Debug.Log($"[Network] Gesture received: {action} (confidence: {payload.confidence:F2})");
            GestureEvents.RaiseGestureReceived(action, payload.confidence);
        }
        catch (Exception e)
        {
            Debug.LogError($"[Network] Failed to parse message: {e.Message}\nRaw: {jsonMessage}");
        }
    }

    public void SendToServer(string message)
    {
        if (mode == ConnectionMode.UDP && udpClient != null)
        {
            byte[] data = Encoding.UTF8.GetBytes(message);
            udpClient.Send(data, data.Length, serverIP, listenPort + 1);
        }
        else if (mode == ConnectionMode.TCP_WebSocket && tcpClient != null && tcpClient.Connected)
        {
            byte[] data = Encoding.UTF8.GetBytes(message);
            tcpClient.GetStream().Write(data, 0, data.Length);
        }
    }

    private void OnDestroy()
    {
        StopListening();
    }

    private void OnApplicationQuit()
    {
        StopListening();
    }

    private void StopListening()
    {
        isRunning = false;
        udpClient?.Close();
        tcpClient?.Close();
        receiveThread?.Join(1000);
    }
}
