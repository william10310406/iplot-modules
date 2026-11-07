REQUIRES = ["numpy", "matplotlib"]              # 用了別的套件就加在這；自己跑一次會自動補
import coursework; coursework.ensure(REQUIRES, __file__)  # 缺的在這一行裝好，裝完才往下 import
import numpy as np

# ── 從這裡開始是作業 ──
NAME = "HK2 二維電場與能量"
DOCS = [("Doc1（台大開放式課程 099S129/39）", "https://ocw.aca.ntu.edu.tw/courses/099S129/39")]
NOTE = """<title>
二維電場與能量的問題
</title>

<content>
1. 物理電學的介紹
2. 數值求解
3. 有限差分的方法

Project. 請用有限元素法, 求解此相同於 case-2 的問題.

</content>

"""
CASES = {
    "case-1": dict(label="電偶極（+1 在 x=-0.5、-1 在 x=0.5）：解析式算電位、電場、能量密度"),
    "case-2": dict(label="一正一負兩個點電荷：有限差分（Jacobi 迭代 2000 次）解 Poisson 方程"),
}


def compute(case):
    """算。純計算、不畫圖、不開視窗；回一個 dict，畫圖和數字都從它拿。"""
    if case == "case-1":
        return _dipole()
    return _poisson_fdm()


def _dipole():
    """case-1：老師 HK2_RUN_CASE1 算的那一段，照抄。"""
    # 1. 建立二維網格空間 (-2 到 2)
    x = np.linspace(-2, 2, 200)
    y = np.linspace(-2, 2, 200)
    X, Y = np.meshgrid(x, y)

    # 2. 設定電荷位置與電量 (電偶極組態)
    q1, pos1 = 1, np.array([-0.5, 0])
    q2, pos2 = -1, np.array([0.5, 0])

    # 避免除以零，加入微小值 eps
    eps = 1e-5
    r1 = np.sqrt((X - pos1[0])**2 + (Y - pos1[1])**2 + eps)
    r2 = np.sqrt((X - pos2[0])**2 + (Y - pos2[1])**2 + eps)

    # 3. 計算電位 V (純量場)
    V = q1/r1 + q2/r2

    # 4. 計算電場 Ex, Ey (向量場)
    Ex = q1*(X - pos1[0]) / r1**3 + q2*(X - pos2[0]) / r2**3
    Ey = q1*(Y - pos1[1]) / r1**3 + q2*(Y - pos2[1]) / r2**3

    # 5. 計算電場能量密度 u
    E_magnitude = np.sqrt(Ex**2 + Ey**2)
    u = 0.5 * (E_magnitude**2)
    return {"case": "case-1", "X": X, "Y": Y, "V": V, "Ex": Ex, "Ey": Ey, "u": u,
            "pos1": pos1, "pos2": pos2}


def _poisson_fdm():
    """case-2：老師 HK2_RUN_CASE2 算的那一段，照抄。"""
    # 1. 參數設定
    Nx, Ny = 50, 50          # 網格點數
    hx, hy = 0.1, 0.1        # 網格間距
    max_iter = 2000          # 最大迭代次數
    eps0 = 1.0               # 真空電容率

    # 初始化電位 V 與電荷密度 rho
    V = np.zeros((Nx, Ny))
    rho = np.zeros((Nx, Ny))

    # 2. 設定內部電荷分佈 (正電荷在 15, 負電荷在 35)
    rho[15, 25] = 10.0
    rho[35, 25] = -10.0

    # 3. FDM 迭代求解帕松方程式 (使用雅可比迭代)
    h2 = hx * hy
    for _ in range(max_iter):
        V_old = V.copy()
        # 僅更新內部點，保持邊界固定為 0
        V[1:-1, 1:-1] = 0.25 * (V_old[2:, 1:-1] + V_old[:-2, 1:-1] +
                                V_old[1:-1, 2:] + V_old[1:-1, :-2] +
                                h2 * rho[1:-1, 1:-1] / eps0)

    # 4. 計算電場 E = -grad V (利用中心差分)
    Ex = np.zeros_like(V)
    Ey = np.zeros_like(V)
    Ex[1:-1, 1:-1] = - (V[2:, 1:-1] - V[:-2, 1:-1]) / (2 * hx)
    Ey[1:-1, 1:-1] = - (V[1:-1, 2:] - V[1:-1, :-2]) / (2 * hy)

    # 5. 計算能量密度 u
    u = 0.5 * eps0 * (Ex**2 + Ey**2)

    # 6. 建立繪圖網格
    x = np.arange(Nx) * hx
    y = np.arange(Ny) * hy
    return {"case": "case-2", "x": x, "y": y, "V": V, "Ex": Ex, "Ey": Ey, "u": u,
            "hx": hx, "hy": hy, "max_iter": max_iter}


def draw(fig, run):
    """畫。在給你的 fig 上畫；兩個 case 都是靜態圖，回 None。"""
    if run["case"] == "case-1":
        X, Y, V, Ex, Ey, u = run["X"], run["Y"], run["V"], run["Ex"], run["Ey"], run["u"]
        pos1, pos2 = run["pos1"], run["pos2"]
        # 6. 繪製模擬結果圖
        ax = fig.add_subplot(1, 1, 1)
        # 繪製能量密度熱度圖 (對數尺度避免中心電荷數值過大)
        pcm = ax.pcolormesh(X, Y, np.log10(u + 1), cmap='inferno', shading='auto')
        fig.colorbar(pcm, ax=ax, label='Log10(Energy Density u)')  # 舊格式只有 ich==0 那段有這條 colorbar

        # 繪製等位線
        contours = ax.contour(X, Y, V, levels=np.linspace(-3, 3, 21), colors='white', linewidths=0.8)
        ax.clabel(contours, inline=True, fontsize=8)

        # 繪製電場線 (使用流線圖 streamplot)
        ax.streamplot(X, Y, Ex, Ey, color='cyan', linewidth=0.8, density=1.2, arrowstyle='->')

        # 標示電荷位置
        ax.scatter([pos1[0]], [pos1[1]], color='red', marker='+', s=200, label='q = +1')
        ax.scatter([pos2[0]], [pos2[1]], color='blue', marker='_', s=200, label='q = -1')

        ax.set_title('2D Electric Field, Potential Lines & Energy Density')
        ax.set_xlabel('X coordinate')
        ax.set_ylabel('Y coordinate')
        ax.legend()
        ax.axis('equal')
        return None

    x, y, V, Ex, Ey, u = run["x"], run["y"], run["V"], run["Ex"], run["Ey"], run["u"]
    hx, hy = run["hx"], run["hy"]
    # 7. 繪製二維結果
    axes = [[] for ii in range(2*1)]
    # 子圖 1: 電位與電場線
    axes[0] = fig.add_subplot(1, 2, 1)
    # 修正處：將 'rdby_r' 改為正確的 'RdBu_r'
    # 照 ich==0（老師要畫的）：colorbar 取 contourf 自己的；舊格式 ich==1 那段多疊了兩張 jet、0 到 1 的
    # pcolormesh，把電位圖整個蓋成深藍，不照抄
    im0 = axes[0].contourf(x, y, V.T, levels=30, cmap='RdBu_r')
    fig.colorbar(im0, ax=axes[0], label='Potential V (V)')

    axes[0].streamplot(x, y, Ex.T, Ey.T, color='black', linewidth=0.6)
    axes[0].scatter([15*hx, 35*hx], [25*hy, 25*hy], color=['red', 'blue'], marker='o', s=50, label='Charges')
    axes[0].set_title('Potential Contour & Field Lines (FDM)', fontsize=6)
    axes[0].set_xlabel('x')
    axes[0].set_ylabel('y')
    axes[0].axis('equal')

    # 子圖 2: 能量密度分佈
    axes[1] = fig.add_subplot(1, 2, 2)
    im1 = axes[1].contourf(x, y, np.log10(u.T + 1e-6), levels=30, cmap='inferno')
    fig.colorbar(im1, ax=axes[1], label='log10(Energy Density u)')
    axes[1].set_title('Energy Density Distribution', fontsize=6)
    axes[1].set_xlabel('x')
    axes[1].set_ylabel('y')
    axes[1].axis('equal')
    fig.tight_layout()
    return None


def stats(run):
    """幾個數字，頁面照順序列。"""
    V, u = run["V"], run["u"]
    out = [("網格點數", " × ".join(str(n) for n in V.shape))]
    if "max_iter" in run:
        out.append(("Jacobi 迭代", f"{run['max_iter']} 次"))
    out += [("電位 V", f"{V.min():.4g} 到 {V.max():.4g}"), ("能量密度 u 最大", f"{u.max():.4g}")]
    return out


# ── 以下不用改 ──
HOMEWORK = dict(name=NAME, docs=DOCS, note=NOTE, cases=CASES, compute=compute, draw=draw, stats=stats, file=__file__)
if __name__ == "__main__":
    raise SystemExit(coursework.main(HOMEWORK))
