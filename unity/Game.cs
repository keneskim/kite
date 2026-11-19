using UnityEngine;

// 由 kite 自动生成。改游戏请改 .kite 源文件。
public class Game : MonoBehaviour
{
    Rigidbody2D _rb;
    Collider2D _col;

    void Start()
    {
        _rb = GetComponent<Rigidbody2D>();
        _col = GetComponent<Collider2D>();
        if (_rb != null) _rb.freezeRotation = true;
        Debug.Log(("游戏开始，速度 " + S(speed())));
    }

    void Update()
    {
        double s = speed();
        if ((Key("left") != 0))
        {
            MoveX(((0.0) - (s)));
        }
        if ((Key("right") != 0))
        {
            MoveX(s);
        }
        if ((B((Key("space") != 0) && (OnGround() != 0)) != 0))
        {
            Jump(12.0);
        }
        if ((B((Y()) < ((-(10.0)))) != 0))
        {
            SetPos(0.0, 2.0);
            Debug.Log("掉下去了，拉回来");
        }
        double t = clamp(Y(), (-(100.0)), 100.0);
        if ((B((t) > (50.0)) != 0))
        {
            Debug.Log("太高了");
        }
    }

    double clamp(double v, double lo, double hi)
    {
        if ((B((v) < (lo)) != 0))
        {
            return lo;
        }
        if ((B((v) > (hi)) != 0))
        {
            return hi;
        }
        return v;
    }

    double speed()
    {
        return 7.0;
    }


    // ---------------- kite 内置 ----------------

    static double B(bool v) { return v ? 1.0 : 0.0; }
    static string S(double v) { return v.ToString(); }
    static string S(string v) { return v; }

    double X() { return transform.position.x; }
    double Y() { return transform.position.y; }

    void SetPos(double x, double y)
    {
        transform.position = new Vector3((float)x, (float)y, transform.position.z);
    }

    void MoveX(double v)
    {
        if (_rb == null) return;
        _rb.velocity = new Vector2((float)v, _rb.velocity.y);
    }

    void Jump(double v)
    {
        if (_rb == null) return;
        _rb.velocity = new Vector2(_rb.velocity.x, (float)v);
    }

    double Key(string name)
    {
        KeyCode k;
        switch (name)
        {
            case "left":  k = KeyCode.LeftArrow; break;
            case "right": k = KeyCode.RightArrow; break;
            case "up":    k = KeyCode.UpArrow; break;
            case "down":  k = KeyCode.DownArrow; break;
            case "space": k = KeyCode.Space; break;
            case "a":     k = KeyCode.A; break;
            case "d":     k = KeyCode.D; break;
            case "w":     k = KeyCode.W; break;
            case "s":     k = KeyCode.S; break;
            default:      k = KeyCode.Space; break;
        }
        return Input.GetKey(k) ? 1.0 : 0.0;
    }

    double OnGround()
    {
        if (_col == null) return 0;
        Vector2 feet = new Vector2(_col.bounds.center.x, _col.bounds.min.y);
        RaycastHit2D hit = Physics2D.Raycast(feet, Vector2.down, 0.12f);
        return (hit.collider != null && hit.collider != _col) ? 1.0 : 0.0;
    }

}