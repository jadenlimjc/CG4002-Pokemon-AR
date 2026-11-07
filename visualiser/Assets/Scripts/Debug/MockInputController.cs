using UnityEngine;

public class MockInputController : MonoBehaviour
{
    [Header("Enable/Disable")]
    [SerializeField] private bool enableMockInput = true;

    [Header("Mock Confidence")]
    [SerializeField] private float mockConfidence = 0.95f;

    private void OnGUI()
    {
        if (!enableMockInput) return;

        Event e = Event.current;
        if (e != null && e.isKey)
        {
            Debug.Log($"[MockInput] Event detected: type={e.type} key={e.keyCode}");
        }
        if (e != null && e.type == EventType.KeyDown)
        {
            switch (e.keyCode)
            {
                case KeyCode.A:
                    if (GameStateManager.Instance != null &&
                        GameStateManager.Instance.CurrentPhase == GamePhase.BattleActive)
                    {
                        Debug.Log("[MockInput] BATTLE_CATCH + ARM_PULLBACK triggered");
                        GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_CATCH, mockConfidence);
                    }
                    else
                    {
                        Debug.Log("[MockInput] ARM_PULLBACK triggered (show reticle)");
                    }
                    GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
                    break;
                case KeyCode.C:
                    Debug.Log("[MockInput] CATCH_THROW triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
                    break;
                case KeyCode.X:
                    Debug.Log("[MockInput] CANCEL triggered (hide reticle)");
                    GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
                    break;
                case KeyCode.B:
                    Debug.Log("[MockInput] POKEBALL_THROW triggered (battle entry)");
                    GestureEvents.RaiseGestureReceived(GestureAction.POKEBALL_THROW, mockConfidence);
                    break;
                case KeyCode.Alpha1:
                    Debug.Log("[MockInput] BATTLE_MOVE_1: Close Combat");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
                    break;
                case KeyCode.Alpha2:
                    Debug.Log("[MockInput] BATTLE_MOVE_2: Protect");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
                    break;
                case KeyCode.Alpha3:
                    Debug.Log("[MockInput] BATTLE_MOVE_3: Brick Break");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
                    break;
                case KeyCode.Alpha4:
                    Debug.Log("[MockInput] BATTLE_MOVE_4: Drain Punch");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
                    break;
                case KeyCode.R:
                    Debug.Log("[MockInput] RESET to Idle");
                    GameStateManager.Instance.ResetToIdle();
                    break;
                case KeyCode.T:
                    Debug.Log("[MockInput] SET_TUTORIAL triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_TUTORIAL, mockConfidence);
                    break;
                case KeyCode.G:
                    Debug.Log("[MockInput] SET_GOD_MODE triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_GOD_MODE, mockConfidence);
                    break;
                case KeyCode.P:
                    Debug.Log("[MockInput] SET_FULL_PLAY triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_FULL_PLAY, mockConfidence);
                    break;
                case KeyCode.S:
                    Debug.Log("[MockInput] SKIP_STEP triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SKIP_STEP, mockConfidence);
                    break;
                case KeyCode.Q:
                    Debug.Log("[MockInput] Toggle PairingUI");
                    if (PairingUI.Instance != null)
                    {
                        if (PairingUI.Instance.IsVisible)
                            PairingUI.Instance.Hide();
                        else
                            PairingUI.Instance.Show();
                    }
                    break;
            }
        }

        GUILayout.BeginArea(new Rect(Screen.width - 310, Screen.height - 260, 300, 250));
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
        GUILayout.Label("[T] Tutorial  [G] God Mode  [P] Full Play");
        GUILayout.Label("[S] Skip Tutorial Step");
        GUILayout.Label("[Q] Toggle Pairing UI");
        GUILayout.Label("");
        GUILayout.Label($"Mode: {DemoModeManager.Instance?.CurrentMode}");
        GUILayout.Label($"Network: {(NetworkManager.Instance?.IsConnected == true ? "Connected" : "Disconnected")}");
        GUILayout.Label($"Paired: {(NetworkManager.Instance?.IsPaired == true ? "Player " + NetworkManager.Instance.PairedDeviceId : "No")}");
        GUILayout.EndArea();
    }
}
