using System;

namespace CG4002.Comms
{
    public enum PairingState
    {
        Unpaired,
        Acquiring,
        Paired
    }

    public sealed class PairableDevice
    {
        public string DeviceId { get; }
        public bool IsOnline { get; }
        public string LastStatus { get; }
        public DateTime LastSeenUtc { get; }

        internal PairableDevice(string deviceId, bool isOnline, string lastStatus, DateTime lastSeenUtc)
        {
            DeviceId = deviceId;
            IsOnline = isOnline;
            LastStatus = lastStatus;
            LastSeenUtc = lastSeenUtc;
        }
    }

    public sealed class PairingResult
    {
        public string RequestId { get; }
        public string Status { get; }
        public string DeviceId { get; }
        public long LeaseExpiresAtMs { get; }
        public long LeaseRemainingMs { get; }
        public string Detail { get; }
        public bool Succeeded => Status == "ACQUIRED" || Status == "RECLAIMED" ||
                                 Status == "RENEWED" || Status == "RELEASED";

        internal PairingResult(PairingWireResult wire)
        {
            RequestId = wire.request_id;
            Status = wire.status;
            DeviceId = wire.device_id;
            LeaseExpiresAtMs = wire.lease_expires_at_ms;
            LeaseRemainingMs = wire.lease_remaining_ms;
            Detail = wire.detail;
        }
    }

    [Serializable]
    internal sealed class PairingRequest
    {
        public string action;
        public string request_id;
        public string device_id;
    }

    [Serializable]
    internal sealed class PairingWireResult
    {
        public string request_id;
        public string status;
        public string device_id;
        public long lease_expires_at_ms = 0;
        public long lease_remaining_ms;
        public string detail;
    }

    [Serializable]
    internal sealed class DeviceStatusPayload
    {
        public string state = null;
    }

    [Serializable]
    internal sealed class MenuControlsPayload
    {
        public int flags;
        public long sequence = -1;
    }
}
