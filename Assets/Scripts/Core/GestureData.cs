using System;

[Serializable]
public enum GestureAction
{
    NONE,
    ARM_PULLBACK,       // Arm draws back -> show reticle, enter aiming
    CATCH_THROW,        // Overhead throw release -> fire pokeball (check aim)
    POKEBALL_THROW,     // Underhand throw motion -> send out own pokemon for battle
    BATTLE_MOVE_1,      // Many punches -> Close Combat
    BATTLE_MOVE_2,      // Block stance -> Protect
    BATTLE_MOVE_3,      // Up-to-down motion -> Brick Break
    BATTLE_MOVE_4,      // Single punch -> Drain Punch / Mach Punch
    CANCEL              // Cancel current action / hand drops without throw
}

[Serializable]
public class GesturePayload
{
    public string action;
    public int gesture_id;
    public float confidence;
    public long timestamp;

    public GestureAction GetGestureAction()
    {
        return action switch
        {
            "ARM_PULLBACK" => GestureAction.ARM_PULLBACK,
            "CATCH_THROW" => GestureAction.CATCH_THROW,
            "POKEBALL_THROW" => GestureAction.POKEBALL_THROW,
            "BATTLE_MOVE" => gesture_id switch
            {
                1 => GestureAction.BATTLE_MOVE_1,
                2 => GestureAction.BATTLE_MOVE_2,
                3 => GestureAction.BATTLE_MOVE_3,
                4 => GestureAction.BATTLE_MOVE_4,
                _ => GestureAction.NONE
            },
            "CANCEL" => GestureAction.CANCEL,
            _ => GestureAction.NONE
        };
    }
}

public static class GestureEvents
{
    public delegate void GestureReceivedHandler(GestureAction action, float confidence);
    public static event GestureReceivedHandler OnGestureReceived;

    public static void RaiseGestureReceived(GestureAction action, float confidence)
    {
        OnGestureReceived?.Invoke(action, confidence);
    }
}
