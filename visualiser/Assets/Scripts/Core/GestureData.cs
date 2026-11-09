using System;

[Serializable]
public enum GestureAction
{
    NONE,
    ARM_PULLBACK,       // Arm draws back -> show reticle, enter aiming
    CATCH_THROW,        // Overhead throw release -> fire pokeball (check aim)
    BATTLE_THROW,       // Overhead throw with button click -> send out own pokemon for battle
    BATTLE_MOVE_1,      // Many punches -> Close Combat
    BATTLE_MOVE_2,      // Block stance -> Protect
    BATTLE_MOVE_3,      // Up-to-down motion -> Brick Break
    BATTLE_MOVE_4,      // Single punch -> Drain Punch / Mach Punch
    BATTLE_RUN,         // Flee from battle
    PARTY_POKEMON,      // View party / switch active pokemon
    BATTLE_ITEM,        // Use an item
    BATTLE_CATCH,       // Initiate catch sequence mid-battle
    CANCEL,             // Cancel current action / hand drops without throw
    SET_TUTORIAL,       // Switch to Tutorial mode (sent from comms manager)
    SET_GOD_MODE,       // Switch to God mode (sent from comms manager)
    SET_FULL_PLAY,      // Switch to Full Play mode (sent from comms manager)
    SKIP_STEP           // Skip current tutorial step (sent from comms manager)
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
            "POKEBALL_THROW" => GestureAction.BATTLE_THROW,
            "BATTLE_MOVE" => gesture_id switch
            {
                1 => GestureAction.BATTLE_MOVE_1,
                2 => GestureAction.BATTLE_MOVE_2,
                3 => GestureAction.BATTLE_MOVE_3,
                4 => GestureAction.BATTLE_MOVE_4,
                _ => GestureAction.NONE
            },
            "BATTLE_ACTION" => gesture_id switch
            {
                1 => GestureAction.BATTLE_RUN,
                2 => GestureAction.PARTY_POKEMON,
                3 => GestureAction.BATTLE_ITEM,
                4 => GestureAction.BATTLE_CATCH,
                _ => GestureAction.NONE
            },
            "CANCEL" => GestureAction.CANCEL,
            "SET_TUTORIAL" => GestureAction.SET_TUTORIAL,
            "SET_GOD_MODE" => GestureAction.SET_GOD_MODE,
            "SET_FULL_PLAY" => GestureAction.SET_FULL_PLAY,
            "SKIP_STEP" => GestureAction.SKIP_STEP,
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
