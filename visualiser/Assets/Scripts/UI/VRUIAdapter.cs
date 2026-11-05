using UnityEngine;

public class VRUIAdapter : MonoBehaviour
{
    [Header("Canvases to adapt")]
    [SerializeField] private Canvas[] uiCanvases;

    [Header("World Space VR Settings")]
    [SerializeField] private float planeDistance = 2f;
    [SerializeField] private float worldScale = 0.001f;

    private RenderMode[] originalModes;
    private Camera[] originalCameras;
    private float[] originalPlaneDistances;
    private Transform[] originalParents;
    private Vector3[] originalScales;
    private Vector3[] originalPositions;

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
        originalScales = new Vector3[uiCanvases.Length];
        originalPositions = new Vector3[uiCanvases.Length];

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;
            originalModes[i] = uiCanvases[i].renderMode;
            originalCameras[i] = uiCanvases[i].worldCamera;
            originalPlaneDistances[i] = uiCanvases[i].planeDistance;
            originalParents[i] = uiCanvases[i].transform.parent;
            originalScales[i] = uiCanvases[i].transform.localScale;
            originalPositions[i] = uiCanvases[i].transform.localPosition;
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
            uiCanvases[i].transform.SetParent(cam.transform, false);
            uiCanvases[i].transform.localPosition = new Vector3(0f, 0f, planeDistance);
            uiCanvases[i].transform.localRotation = Quaternion.identity;
            uiCanvases[i].transform.localScale = Vector3.one * worldScale;
        }
    }

    private void RestoreOriginal()
    {
        if (originalModes == null) return;

        for (int i = 0; i < uiCanvases.Length; i++)
        {
            if (uiCanvases[i] == null) continue;

            if (originalParents[i] != null)
                uiCanvases[i].transform.SetParent(originalParents[i], false);

            uiCanvases[i].transform.localPosition = originalPositions[i];
            uiCanvases[i].transform.localScale = originalScales[i];
            uiCanvases[i].renderMode = originalModes[i];
            uiCanvases[i].worldCamera = originalCameras[i];
            uiCanvases[i].planeDistance = originalPlaneDistances[i];
        }
    }
}
