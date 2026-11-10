using UnityEngine;

[DefaultExecutionOrder(100)]
public class VRUIAdapter : MonoBehaviour
{
    [Header("Canvas")]
    [SerializeField] private Canvas mainCanvas;

    [Header("VR Layout - Bottom Bar (battle controls)")]
    [SerializeField] private RectTransform battlePanel;

    [Header("VR Layout - Left Bar")]
    [SerializeField] private RectTransform modeSelectPanel;

    [Header("VR Layout - Center Gap")]
    [SerializeField] private RectTransform pairingPanel;
    [SerializeField] private RectTransform partyMenuPanel;

    private bool isVRActive;
    private int originalSortingOrder;

    private struct PanelState
    {
        public Vector2 anchorMin;
        public Vector2 anchorMax;
        public Vector2 anchoredPosition;
        public Vector2 sizeDelta;
    }

    private RectTransform[] panels;
    private PanelState[] originalStates;

    private void OnEnable()
    {
        if (VRModeManager.Instance != null)
            VRModeManager.Instance.OnVRModeChanged += HandleVRModeChanged;
    }

    private void OnDisable()
    {
        if (VRModeManager.Instance != null)
            VRModeManager.Instance.OnVRModeChanged -= HandleVRModeChanged;
    }

    private void Start()
    {
        if (VRModeManager.Instance != null)
        {
            VRModeManager.Instance.OnVRModeChanged -= HandleVRModeChanged;
            VRModeManager.Instance.OnVRModeChanged += HandleVRModeChanged;
        }

        panels = new[] { battlePanel, modeSelectPanel, pairingPanel, partyMenuPanel };
        CacheOriginalStates();
    }

    private void CacheOriginalStates()
    {
        originalStates = new PanelState[panels.Length];
        for (int i = 0; i < panels.Length; i++)
        {
            if (panels[i] == null) continue;
            originalStates[i] = new PanelState
            {
                anchorMin = panels[i].anchorMin,
                anchorMax = panels[i].anchorMax,
                anchoredPosition = panels[i].anchoredPosition,
                sizeDelta = panels[i].sizeDelta,
            };
        }
    }

    private void HandleVRModeChanged(bool isVR)
    {
        if (isVR)
            ApplyVRLayout();
        else
            RestoreLayout();
    }

    private void ApplyVRLayout()
    {
        isVRActive = true;

        if (mainCanvas != null)
        {
            originalSortingOrder = mainCanvas.sortingOrder;
            mainCanvas.sortingOrder = 999;
        }

        float s = VRModeManager.Instance != null ? VRModeManager.Instance.LensScaleFactor : 0.6f;

        float yBot = (1f - s) / 2f;
        float yTop = 1f - yBot;
        float leftBarRight = (1f - s) / 4f;
        float leftViewRight = (1f + s) / 4f;
        float rightViewLeft = 0.5f + (1f - s) / 4f;

        SetAnchors(battlePanel, 0.05f, 0.01f, 0.95f, yBot - 0.01f);
        SetAnchors(modeSelectPanel, 0.01f, yBot + 0.02f, leftBarRight - 0.01f, yTop - 0.02f);
        SetAnchors(pairingPanel, leftViewRight + 0.01f, yBot + 0.02f, rightViewLeft - 0.01f, yTop - 0.02f);
        SetAnchors(partyMenuPanel, leftViewRight + 0.01f, yBot + 0.02f, rightViewLeft - 0.01f, yTop - 0.02f);
    }

    private void RestoreLayout()
    {
        isVRActive = false;

        if (mainCanvas != null)
            mainCanvas.sortingOrder = originalSortingOrder;

        if (originalStates == null) return;
        for (int i = 0; i < panels.Length; i++)
        {
            if (panels[i] == null) continue;
            panels[i].anchorMin = originalStates[i].anchorMin;
            panels[i].anchorMax = originalStates[i].anchorMax;
            panels[i].anchoredPosition = originalStates[i].anchoredPosition;
            panels[i].sizeDelta = originalStates[i].sizeDelta;
        }
    }

    private void SetAnchors(RectTransform rt, float xMin, float yMin, float xMax, float yMax)
    {
        if (rt == null) return;
        rt.anchorMin = new Vector2(xMin, yMin);
        rt.anchorMax = new Vector2(xMax, yMax);
        rt.anchoredPosition = Vector2.zero;
        rt.sizeDelta = Vector2.zero;
    }
}
