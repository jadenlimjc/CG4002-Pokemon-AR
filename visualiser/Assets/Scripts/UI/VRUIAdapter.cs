using UnityEngine;

public class VRUIAdapter : MonoBehaviour
{
    [Header("Canvases to adapt")]
    [SerializeField] private Canvas[] uiCanvases;

    [Header("Screen Space Camera Settings")]
    [SerializeField] private float planeDistance = 1f;

    private RenderMode[] originalModes;
    private Camera[] originalCameras;
    private float[] originalPlaneDistances;
    private Transform[] originalParents;

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
        originalPlaneDistances = new float[uiCanvases.Length];
        originalParents = new Transform[uiCanvases.Length];

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;
            originalModes[i] = uiCanvases[i].renderMode;
            originalCameras[i] = uiCanvases[i].worldCamera;
            originalPlaneDistances[i] = uiCanvases[i].planeDistance;
            originalParents[i] = uiCanvases[i].transform.parent;
        }
    }

    private void HandleVRModeChanged(bool isVR)
    {
        if (uiCanvases == null) return;

        if (isVR)
            SwitchToScreenSpaceCamera();
        else
            RestoreOriginal();
    }

    private void SwitchToScreenSpaceCamera()
    {
        Camera cam = Camera.main;
        if (cam == null) return;

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;

            uiCanvases[i].renderMode = RenderMode.ScreenSpaceCamera;
            uiCanvases[i].worldCamera = cam;
            uiCanvases[i].planeDistance = planeDistance;
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
            uiCanvases[i].planeDistance = originalPlaneDistances[i];
            if (originalParents[i] != null)
                uiCanvases[i].transform.SetParent(originalParents[i], false);
        }
    }
}
