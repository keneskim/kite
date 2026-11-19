using UnityEngine;

// 拖到 Main Camera 上，把 Player 拖进 target 格子。
public class CameraFollow : MonoBehaviour
{
    public Transform target;      // 玩家
    public float smooth = 5f;     // 越大跟得越紧

    void LateUpdate()
    {
        if (target == null) return;
        Vector3 want = new Vector3(target.position.x,
                                   target.position.y,
                                   transform.position.z);
        transform.position = Vector3.Lerp(transform.position, want,
                                          smooth * Time.deltaTime);
    }
}
