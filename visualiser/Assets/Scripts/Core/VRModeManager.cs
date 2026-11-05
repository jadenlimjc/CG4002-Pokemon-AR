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


    [Header("Optical Zoom Compensation")]
    [Tooltip("Values greater than 1.0 widen the FOV to counteract heavily magnified lenses.")]
    [SerializeField] private float fovMultiplier = 1.5f;

    private float originalFOV;

    private const int AR_MESH_LAYER = 25;

    public bool IsVRMode { get; private set; }

    public delegate void VRModeChangedHandler(bool isVR);
    public event VRModeChangedHandler OnVRModeChanged;

    private Camera mainCamera;
    private Camera rightEyeCamera;
    private GameObject rightEyeObject;
    private Vector3 originalLocalPosition;
    private ScreenOrientation originalOrientation;
    private Coroutine meshLayerCoroutine;

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

    private void LateUpdate()
    {
        if (!IsVRMode || mainCamera == null || rightEyeCamera == null) return;

        rightEyeCamera.nearClipPlane = mainCamera.nearClipPlane;
        rightEyeCamera.farClipPlane = mainCamera.farClipPlane;

        //Left Eye Projection & FOV Compensation
        Matrix4x4 leftProj = mainCamera.projectionMatrix;
        
        if (IsVRMode)
        {
            // Scale projection matrix diagonals to widen/narrow the FOV (counteracting mobile hardware overrides)
            leftProj[0, 0] /= fovMultiplier; // Horizontal FOV scale
            leftProj[1, 1] /= fovMultiplier; // Vertical FOV scale
        }

        leftProj[0, 2] += projectionOffset;
        mainCamera.projectionMatrix = leftProj;

        // Right Eye Projection
        rightEyeCamera.ResetProjectionMatrix();
        Matrix4x4 rightProj = rightEyeCamera.projectionMatrix;
        
        if (IsVRMode)
        {
            rightProj[0, 0] /= fovMultiplier;
            rightProj[1, 1] /= fovMultiplier;
        }

        rightProj[0, 2] -= projectionOffset;
        rightEyeCamera.projectionMatrix = rightProj;
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

        CreateRightEyeCamera();

        SetARMeshLayer(AR_MESH_LAYER);
        meshLayerCoroutine = StartCoroutine(PeriodicMeshLayerUpdate());

        OnVRModeChanged?.Invoke(true);
        Debug.Log("[VR] VR mode enabled");
    }

    private void DisableVR()
    {
        if (!IsVRMode) return;
        IsVRMode = false;

        if (meshLayerCoroutine != null)
        {
            StopCoroutine(meshLayerCoroutine);
            meshLayerCoroutine = null;
        }
        SetARMeshLayer(0);

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
        rightEyeObject.transform.SetParent(mainCamera.transform, false);

        rightEyeCamera = rightEyeObject.AddComponent<Camera>();
        rightEyeCamera.CopyFrom(mainCamera);
        rightEyeCamera.ResetWorldToCameraMatrix();
        rightEyeCamera.ResetProjectionMatrix();
        rightEyeCamera.rect = new Rect(0.5f, 0f, 0.5f, 1f);
        rightEyeCamera.tag = "Untagged";
        rightEyeCamera.depth = mainCamera.depth + 1;
        rightEyeCamera.cullingMask = mainCamera.cullingMask & ~(1 << AR_MESH_LAYER);

        var mainBg = mainCamera.GetComponent<ARCameraBackground>();
        if (mainBg != null)
        {
            var rightBg = rightEyeObject.AddComponent<ARCameraBackground>();
            rightBg.useCustomMaterial = mainBg.useCustomMaterial;
            rightBg.customMaterial = mainBg.customMaterial;
        }
        else
        {
            rightEyeCamera.clearFlags = CameraClearFlags.SolidColor;
            rightEyeCamera.backgroundColor = Color.black;
        }

        rightEyeObject.transform.localPosition = new Vector3(ipd, 0f, 0f);
        rightEyeObject.transform.localRotation = Quaternion.identity;

        Debug.Log($"[VR] Right eye created - localPos: {rightEyeObject.transform.localPosition}, ipd: {ipd}");
    }

    private void SetARMeshLayer(int layer)
    {
        foreach (var filter in FindObjectsByType<MeshFilter>(FindObjectsSortMode.None))
        {
            if (filter.GetComponent<MeshCollider>() != null)
                filter.gameObject.layer = layer;
        }
    }

    private IEnumerator PeriodicMeshLayerUpdate()
    {
        while (true)
        {
            yield return new WaitForSeconds(2f);
            SetARMeshLayer(AR_MESH_LAYER);
        }
    }

    private void OnDestroy()
    {
        if (IsVRMode)
            DisableVR();
    }
}
