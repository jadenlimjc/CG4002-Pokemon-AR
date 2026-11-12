using UnityEngine;
using UnityEngine.UI;

public class CrosshairUI : Graphic
{
    [SerializeField] private float thickness = 2f;
    [SerializeField] private float size = 40f;
    [SerializeField] private float gap = 8f;

    private Color _targetColor = Color.white;
    private Color _currentColor = Color.white;

    public void SetHighlight(bool hasTarget)
    {
        _targetColor = hasTarget ? Color.green : Color.white;
    }

    private void Update()
    {
        if (_currentColor != _targetColor)
        {
            _currentColor = Color.Lerp(_currentColor, _targetColor, Time.deltaTime * 12f);
            color = new Color(_currentColor.r, _currentColor.g, _currentColor.b, 0.9f);
        }
    }

    protected override void OnPopulateMesh(VertexHelper vh)
    {
        vh.Clear();

        float half = thickness * 0.5f;

        AddRect(vh, -size, -half, -gap, half);
        AddRect(vh, gap, -half, size, half);
        AddRect(vh, -half, -size, half, -gap);
        AddRect(vh, -half, gap, half, size);

        float dotHalf = thickness;
        AddRect(vh, -dotHalf, -dotHalf, dotHalf, dotHalf);
    }

    private void AddRect(VertexHelper vh, float xMin, float yMin, float xMax, float yMax)
    {
        int idx = vh.currentVertCount;

        vh.AddVert(new Vector3(xMin, yMin), color, Vector2.zero);
        vh.AddVert(new Vector3(xMin, yMax), color, Vector2.up);
        vh.AddVert(new Vector3(xMax, yMax), color, Vector2.one);
        vh.AddVert(new Vector3(xMax, yMin), color, Vector2.right);

        vh.AddTriangle(idx, idx + 1, idx + 2);
        vh.AddTriangle(idx, idx + 2, idx + 3);
    }
}
