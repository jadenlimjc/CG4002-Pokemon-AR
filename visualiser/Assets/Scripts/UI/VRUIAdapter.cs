using UnityEngine;

public class VRUIAdapter : MonoBehaviour
{
    [Header("Canvases to adapt")]
    [SerializeField] private Canvas[] uiCanvases;

    [Header("World Space Settings")]
    [SerializeField] private float canvasDistance = 2f;
    [SerializeField] private float canvasScale = 0.002f;

    private RenderMode[] originalModes;
    private Camera[] originalCameras;
    private Vector3[] originalScales;

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

        CacheOriginalSettings();
    }

    private void CacheOriginalSettings()
    {
        if (uiCanvases == null || uiCanvases.Length == 0) return;

        originalModes = new RenderMode[uiCanvases.Length];
        originalCameras = new Camera[uiCanvases.Length];
        originalScales = new Vector3[uiCanvases.Length];

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;
            originalModes[i] = uiCanvases[i].renderMode;
            originalCameras[i] = uiCanvases[i].worldCamera;
            originalScales[i] = uiCanvases[i].transform.localScale;
        }
    }

    private void HandleVRModeChanged(bool isVR)
    {
        if (uiCanvases == null) return;

        if (isVR)
            SwitchToWorldSpace();
        else
            RestoreOriginal();
    }

    private void SwitchToWorldSpace()
    {
        Camera cam = Camera.main;
        if (cam == null) return;

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;

            uiCanvases[i].renderMode = RenderMode.WorldSpace;
            uiCanvases[i].worldCamera = cam;

            Transform canvasTransform = uiCanvases[i].transform;
            canvasTransform.SetParent(cam.transform.parent, false);
            canvasTransform.localScale = Vector3.one * canvasScale;
            canvasTransform.localPosition = Vector3.forward * canvasDistance;
            canvasTransform.localRotation = Quaternion.identity;
        }
    }

    private void RestoreOriginal()
    {
        if (originalModes == null) return;

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;

            uiCanvases[i].renderMode = originalModes[i];
            uiCanvases[i].worldCamera = originalCameras[i];
            uiCanvases[i].transform.localScale = originalScales[i];
        }
    }
}
