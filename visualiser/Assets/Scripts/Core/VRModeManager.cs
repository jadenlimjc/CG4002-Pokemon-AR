using UnityEngine;
using UnityEngine.XR.ARFoundation;

public class VRModeManager : MonoBehaviour
{
    public static VRModeManager Instance { get; private set; }

    [Header("Settings")]
    [SerializeField] private float ipd = 0.064f;
    [SerializeField] private bool startInVR = false;

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
            EnableVR();
    }

    private void Update()
    {
#if UNITY_EDITOR
        if (Input.GetKeyDown(vrToggleKey))
            ToggleVR();
#endif
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

        OnVRModeChanged?.Invoke(true);
        Debug.Log("[VR] VR mode enabled");
    }

    private void DisableVR()
    {
        if (!IsVRMode) return;
        IsVRMode = false;

        if (mainCamera != null)
        {
            mainCamera.rect = new Rect(0f, 0f, 1f, 1f);
            mainCamera.transform.localPosition = originalLocalPosition;
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

    private void LateUpdate()
    {
        if (!IsVRMode || rightEyeObject == null || mainCamera == null) return;

        rightEyeObject.transform.localRotation = mainCamera.transform.localRotation;
    }

    private void OnDestroy()
    {
        if (IsVRMode)
            DisableVR();
    }
}
