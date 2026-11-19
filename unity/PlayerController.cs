using UnityEngine;

// 把脚本拖到「玩家」方块上。手感参数在 Inspector 里调，不用改代码。
public class PlayerController : MonoBehaviour
{
    [Header("手感：只调这两个数")]
    public float moveSpeed = 6f;      // 跑多快
    public float jumpForce = 11f;     // 跳多高

    [Header("检测地面，一般不用动")]
    public float groundCheck = 0.12f;

    Rigidbody2D rb;
    Collider2D col;

    void Start()
    {
        rb = GetComponent<Rigidbody2D>();
        col = GetComponent<Collider2D>();
        if (rb != null) rb.freezeRotation = true;   // 别让方块摔倒
    }

    void Update()
    {
        if (rb == null) return;

        // 左右移动：直接改速度，手感最直接
        float h = Input.GetAxisRaw("Horizontal");
        rb.velocity = new Vector2(h * moveSpeed, rb.velocity.y);

        // 跳：只在踩在地上时允许
        if (Input.GetButtonDown("Jump") && IsGrounded())
            rb.velocity = new Vector2(rb.velocity.x, jumpForce);
    }

    bool IsGrounded()
    {
        if (col == null) return false;
        Vector2 feet = new Vector2(col.bounds.center.x, col.bounds.min.y);
        RaycastHit2D hit = Physics2D.Raycast(feet, Vector2.down, groundCheck);
        return hit.collider != null && hit.collider != col;
    }
}
