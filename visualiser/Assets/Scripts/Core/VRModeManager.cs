using System.Collections;
using UnityEngine;
using UnityEngine.UI;
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
    [SerializeField] private KeyCode vrToggleKey = KeyCode.O;

    [Header("Zoom Compensation")]
    [Tooltip("UV rect scale for each eye. 1.0 = no change, < 1.0 zooms out. Adjust if VRG Pro lenses still magnify too much.")]
    [SerializeField] private float zoomCompensation = 1.0f;

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

    private RenderTexture leftRT;
    private RenderTexture rightRT;
    private GameObject vrCanvasObject;

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

    private int vrFrameCount;

    private void LateUpdate()
    {
        if (!IsVRMode || mainCamera == null || rightEyeCamera == null) return;

        if (mainCamera.targetTexture != leftRT)
        {
            Debug.Log($"[VR] mainCamera.targetTexture was reset! Re-assigning. Current={mainCamera.targetTexture}");
            mainCamera.targetTexture = leftRT;
        }

        rightEyeCamera.nearClipPlane = mainCamera.nearClipPlane;
        rightEyeCamera.farClipPlane = mainCamera.farClipPlane;

        mainCamera.ResetProjectionMatrix();
        Matrix4x4 leftProj = mainCamera.projectionMatrix;
        leftProj[0, 2] += projectionOffset;
        mainCamera.projectionMatrix = leftProj;

        rightEyeCamera.ResetProjectionMatrix();
        Matrix4x4 rightProj = rightEyeCamera.projectionMatrix;
        rightProj[0, 2] -= projectionOffset;
        rightEyeCamera.projectionMatrix = rightProj;

        vrFrameCount++;
        if (vrFrameCount <= 5)
            Debug.Log($"[VR] Frame {vrFrameCount}: mainCam.targetTex={mainCamera.targetTexture == leftRT}, rightCam.targetTex={rightEyeCamera.targetTexture == rightRT}, mainCam.rect={mainCamera.rect}");
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

        CreateRenderTextures();
        CreateRightEyeCamera();
        CreateVRCanvas();

        mainCamera.rect = new Rect(0f, 0f, 1f, 1f);
        mainCamera.targetTexture = leftRT;

        SetARMeshLayer(AR_MESH_LAYER);
        meshLayerCoroutine = StartCoroutine(PeriodicMeshLayerUpdate());

        OnVRModeChanged?.Invoke(true);
        Debug.Log("[VR] VR mode enabled (render-to-texture)");
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
            mainCamera.targetTexture = null;
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

        if (vrCanvasObject != null)
        {
            Destroy(vrCanvasObject);
            vrCanvasObject = null;
        }

        ReleaseRenderTextures();

        Screen.orientation = originalOrientation;
        Screen.sleepTimeout = SleepTimeout.SystemSetting;

        OnVRModeChanged?.Invoke(false);
        Debug.Log("[VR] VR mode disabled");
    }

    private void CreateRenderTextures()
    {
        int w = Screen.width / 2;
        int h = Screen.height;
        leftRT = new RenderTexture(w, h, 24);
        rightRT = new RenderTexture(w, h, 24);
        leftRT.Create();
        rightRT.Create();
        Debug.Log($"[VR] RenderTextures created: {w}x{h}, leftRT.IsCreated={leftRT.IsCreated()}, rightRT.IsCreated={rightRT.IsCreated()}");
    }

    private void ReleaseRenderTextures()
    {
        if (leftRT != null)
        {
            leftRT.Release();
            Destroy(leftRT);
            leftRT = null;
        }
        if (rightRT != null)
        {
            rightRT.Release();
            Destroy(rightRT);
            rightRT = null;
        }
    }

    private void CreateRightEyeCamera()
    {
        rightEyeObject = new GameObject("RightEyeCamera");
        rightEyeObject.transform.SetParent(mainCamera.transform, false);

        rightEyeCamera = rightEyeObject.AddComponent<Camera>();
        rightEyeCamera.CopyFrom(mainCamera);
        rightEyeCamera.ResetWorldToCameraMatrix();
        rightEyeCamera.ResetProjectionMatrix();
        rightEyeCamera.rect = new Rect(0f, 0f, 1f, 1f);
        rightEyeCamera.targetTexture = rightRT;
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
    }

    private void CreateVRCanvas()
    {
        vrCanvasObject = new GameObject("VRDisplayCanvas");
        var canvas = vrCanvasObject.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 999;

        float uvScale = zoomCompensation;
        float uvOff = (1f - uvScale) / 2f;

        var leftObj = new GameObject("LeftEye");
        leftObj.transform.SetParent(vrCanvasObject.transform, false);
        var leftImage = leftObj.AddComponent<RawImage>();
        leftImage.texture = leftRT;
        leftImage.uvRect = new Rect(uvOff, uvOff, uvScale, uvScale);
        var leftRect = leftObj.GetComponent<RectTransform>();
        leftRect.anchorMin = new Vector2(0f, 0f);
        leftRect.anchorMax = new Vector2(0.5f, 1f);
        leftRect.offsetMin = Vector2.zero;
        leftRect.offsetMax = Vector2.zero;

        var rightObj = new GameObject("RightEye");
        rightObj.transform.SetParent(vrCanvasObject.transform, false);
        var rightImage = rightObj.AddComponent<RawImage>();
        rightImage.texture = rightRT;
        rightImage.uvRect = new Rect(uvOff, uvOff, uvScale, uvScale);
        var rightRect = rightObj.GetComponent<RectTransform>();
        rightRect.anchorMin = new Vector2(0.5f, 0f);
        rightRect.anchorMax = new Vector2(1f, 1f);
        rightRect.offsetMin = Vector2.zero;
        rightRect.offsetMax = Vector2.zero;

        Debug.Log($"[VR] Canvas created: sortingOrder={canvas.sortingOrder}, leftTex={leftImage.texture != null}, rightTex={rightImage.texture != null}");
        Debug.Log($"[VR] mainCamera.targetTexture={mainCamera.targetTexture != null}, rightEye.targetTexture={rightEyeCamera?.targetTexture != null}");
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
