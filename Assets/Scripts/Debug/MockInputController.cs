using UnityEngine;
using UnityEngine.InputSystem;

public class MockInputController : MonoBehaviour
{
    [Header("Enable/Disable")]
    [SerializeField] private bool enableMockInput = true;

    [Header("Mock Confidence")]
    [SerializeField] private float mockConfidence = 0.95f;

    private void Update()
    {
        if (!enableMockInput) return;

        var kb = Keyboard.current;
        if (kb == null) return;

        if (kb.aKey.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] ARM_PULLBACK triggered (show reticle)");
            GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
        }

        if (kb.cKey.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] CATCH_THROW triggered");
            GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
        }

        if (kb.xKey.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] CANCEL triggered (hide reticle)");
            GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
        }

        if (kb.bKey.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] POKEBALL_THROW triggered (battle entry)");
            GestureEvents.RaiseGestureReceived(GestureAction.POKEBALL_THROW, mockConfidence);
        }

        if (kb.digit1Key.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] BATTLE_MOVE_1: Close Combat");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
        }

        if (kb.digit2Key.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] BATTLE_MOVE_2: Protect");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
        }

        if (kb.digit3Key.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] BATTLE_MOVE_3: Brick Break");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
        }

        if (kb.digit4Key.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] BATTLE_MOVE_4: Drain Punch");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
        }

        if (kb.rKey.wasPressedThisFrame)
        {
            Debug.Log("[MockInput] RESET to Idle");
            GameStateManager.Instance.ResetToIdle();
        }
    }

#if UNITY_EDITOR
    private void OnGUI()
    {
        if (!enableMockInput) return;

        GUILayout.BeginArea(new Rect(10, 10, 300, 250));
        GUILayout.Label("=== MOCK INPUT (Debug) ===");
        GUILayout.Label($"State: {GameStateManager.Instance?.CurrentPhase}");
        GUILayout.Label($"Aiming: {(CatchManager.Instance?.IsAiming == true ? "YES" : "no")}");
        GUILayout.Label("");
        GUILayout.Label("[A] Aim (show reticle)");
        GUILayout.Label("[C] Catch Throw (fire ball)");
        GUILayout.Label("[X] Cancel (hide reticle)");
        GUILayout.Label("[B] Battle Entry");
        GUILayout.Label("[1] Move 1: Close Combat");
        GUILayout.Label("[2] Move 2: Protect");
        GUILayout.Label("[3] Move 3: Brick Break");
        GUILayout.Label("[4] Move 4: Drain Punch");
        GUILayout.Label("[R] Reset to Idle");
        GUILayout.Label("");
        GUILayout.Label($"Network: {(NetworkManager.Instance?.IsConnected == true ? "Connected" : "Disconnected")}");
        GUILayout.EndArea();
    }
#endif
}
