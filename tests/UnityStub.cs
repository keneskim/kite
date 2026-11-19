// 假的 UnityEngine，只为了在没有 Unity 的机器上编译验证
namespace UnityEngine
{
    public class Object {}
    public class Component : Object
    {
        public T GetComponent<T>() where T : class { return null; }
        public Transform transform;
    }
    public class Behaviour : Component {}
    public class MonoBehaviour : Behaviour {}
    public class Transform : Component { public Vector3 position; }

    public struct Vector2
    {
        public float x, y;
        public Vector2(float x, float y) { this.x = x; this.y = y; }
        public static Vector2 down { get { return new Vector2(0, -1); } }
    }
    public struct Vector3
    {
        public float x, y, z;
        public Vector3(float x, float y, float z) { this.x = x; this.y = y; this.z = z; }
    }
    public struct Bounds { public Vector3 center, min, extents; }
    public class Rigidbody2D : Component { public Vector2 velocity; public bool freezeRotation; }
    public class Collider2D : Component { public Bounds bounds; }
    public struct RaycastHit2D { public Collider2D collider; }
    public static class Physics2D
    {
        public static RaycastHit2D Raycast(Vector2 origin, Vector2 dir, float dist)
        { return new RaycastHit2D(); }
    }
    public static class Input
    {
        public static bool GetKey(KeyCode k) { return false; }
        public static bool GetKeyDown(KeyCode k) { return false; }
        public static float GetAxisRaw(string axis) { return 0; }
    }
    public enum KeyCode { LeftArrow, RightArrow, UpArrow, DownArrow, Space, A, D, W, S }
    public static class Debug { public static void Log(object o) {} }
    public static class Time { public static float deltaTime; }
}
