using System.Collections;
using UnityEngine;
using UnityEngine.XR.ARFoundation;

public class VRModeManager : MonoBehaviour
{
    public static VRModeManager Instance { get; private set; }

    [Header("Settings")]
    [SerializeField] private float ipd = 0.064f;
    [SerializeField] private bool startInVR = false;

    [Header("Lens Convergence")]
    [Tooltip("How much each eye's projection shifts inward (0.0-0.1). Increase if images won't fuse.")]
    [SerializeField] private float projectionOffset = 0.02f;

    [Header("Editor Testing")]
    [SerializeField] private KeyCode vrToggleKey = KeyCode.V;

    public bool IsVRMode { get; private set; }

    public delegate void VRModeChangedHandler(bool isVR);
    public event VRModeChangedHandler OnVRModeChanged;

    private Camera mainCamera;
    private Camera rightEyeCamera;
    private GameObject rightEyeObject;
    private Vector3 originalLocalPosition;
    private ScreenOrientation originalOrientation;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    private void Start()
    {
        mainCamera = Camera.main;
        if (mainCamera != null)
            originalLocalPosition = mainCamera.transform.localPosition;

        originalOrientation = Screen.orientation;

        if (startInVR)
            StartCoroutine(EnableVRDelayed());
    }

    private void Update()
    {
#if UNITY_EDITOR
        if (Input.GetKeyDown(vrToggleKey))
            ToggleVR();
#endif
    }

    private IEnumerator EnableVRDelayed()
    {
        yield return new WaitForSeconds(1f);
        EnableVR();
    }

    public void ToggleVR()
    {
        if (IsVRMode)
            DisableVR();
        else
            EnableVR();
    }

    private void EnableVR()
    {
        if (IsVRMode) return;
        if (mainCamera == null)
        {
            mainCamera = Camera.main;
            if (mainCamera == null) return;
            originalLocalPosition = mainCamera.transform.localPosition;
        }

        IsVRMode = true;

        Screen.orientation = ScreenOrientation.LandscapeLeft;
        Screen.sleepTimeout = SleepTimeout.NeverSleep;

        mainCamera.rect = new Rect(0f, 0f, 0.5f, 1f);
        mainCamera.transform.localPosition = originalLocalPosition + Vector3.left * (ipd / 2f);

        CreateRightEyeCamera();

        Camera.onPreRender += OnCameraPreRender;

        OnVRModeChanged?.Invoke(true);
        Debug.Log("[VR] VR mode enabled");
    }

    private void DisableVR()
    {
        if (!IsVRMode) return;
        IsVRMode = false;

        Camera.onPreRender -= OnCameraPreRender;

        if (mainCamera != null)
        {
            mainCamera.rect = new Rect(0f, 0f, 1f, 1f);
            mainCamera.transform.localPosition = originalLocalPosition;
            mainCamera.ResetProjectionMatrix();
        }

        if (rightEyeObject != null)
        {
            Destroy(rightEyeObject);
            rightEyeObject = null;
            rightEyeCamera = null;
        }

        Screen.orientation = originalOrientation;
        Screen.sleepTimeout = SleepTimeout.SystemSetting;

        OnVRModeChanged?.Invoke(false);
        Debug.Log("[VR] VR mode disabled");
    }

    private void CreateRightEyeCamera()
    {
        rightEyeObject = new GameObject("RightEyeCamera");
        rightEyeObject.transform.SetParent(mainCamera.transform.parent, false);
        rightEyeObject.transform.localPosition = originalLocalPosition + Vector3.right * (ipd / 2f);
        rightEyeObject.transform.localRotation = mainCamera.transform.localRotation;

        rightEyeCamera = rightEyeObject.AddComponent<Camera>();
        rightEyeCamera.CopyFrom(mainCamera);
        rightEyeCamera.rect = new Rect(0.5f, 0f, 0.5f, 1f);
        rightEyeCamera.tag = "Untagged";
        rightEyeCamera.depth = mainCamera.depth + 1;

        ARCameraBackground mainBg = mainCamera.GetComponent<ARCameraBackground>();
        if (mainBg != null)
        {
            ARCameraBackground rightBg = rightEyeObject.AddComponent<ARCameraBackground>();
            rightBg.useCustomMaterial = mainBg.useCustomMaterial;
            if (mainBg.useCustomMaterial && mainBg.customMaterial != null)
                rightBg.customMaterial = mainBg.customMaterial;
        }
    }

    private void OnCameraPreRender(Camera cam)
    {
        if (!IsVRMode || mainCamera == null) return;

        if (cam == mainCamera)
        {
            // Left eye: read AR Foundation's matrix, shift right (toward nose)
            Matrix4x4 proj = mainCamera.projectionMatrix;
            proj[0, 2] += projectionOffset;
            mainCamera.projectionMatrix = proj;
        }
        else if (cam == rightEyeCamera)
        {
            // Sync right eye with main camera's current settings
            rightEyeCamera.fieldOfView = mainCamera.fieldOfView;
            rightEyeCamera.nearClipPlane = mainCamera.nearClipPlane;
            rightEyeCamera.farClipPlane = mainCamera.farClipPlane;
            rightEyeObject.transform.localRotation = mainCamera.transform.localRotation;

            // Right eye: use main camera's base matrix, shift left (toward nose)
            Matrix4x4 proj = mainCamera.projectionMatrix;
            proj[0, 2] -= projectionOffset;
            rightEyeCamera.projectionMatrix = proj;
        }
    }

    private void OnDestroy()
    {
        Camera.onPreRender -= OnCameraPreRender;
        if (IsVRMode)
            DisableVR();
    }
}
