REQUIRES = ["numpy", "matplotlib"]              # 用了別的套件就加在這；自己跑一次會自動補
import coursework; coursework.ensure(REQUIRES, __file__)  # 缺的在這一行裝好，裝完才往下 import
import numpy as np
from matplotlib.animation import FuncAnimation

# ── 從這裡開始是作業 ──
NAME = "HK6 淺水波：Shallow Water Problems"
DOCS = [
    ("pyro2: shallow water basics", "https://python-hydro.github.io/pyro2/swe_basics.html"),
    ("Burkardt: shallow_water_1d", "https://people.math.sc.edu/Burkardt/py_src/shallow_water_1d/shallow_water_1d.html"),
]
NOTE = """<title>
Shallow Water Problems
</title>

<content>
1. Introduction
2. Python/Matlab
3. Exercises

Project:
</content>
"""
CASES = {
    "case-1": dict(label="1D 潰壩（Lax-Friedrichs）"),
    "case-2": dict(label="2D 水滴擴散（Arakawa C 網格）"),
}


def _case1():
    """舊格式的 HK6_RUN_CASE1：一維淺水方程、潰壩，Lax-Friedrichs。每一步的 h、u 都留在 run 裡。"""
    # --- Simulation Parameters ---
    N = 200            # Number of spatial grid points
    L = 10.0           # Length of the domain
    dx = L / (N - 1)   # Grid spacing
    g = 9.81           # Acceleration due to gravity
    dt = 0.005         # Time step (chosen to satisfy CFL condition)
    num_steps = 400    # Total number of time steps

    # Grid coordinates
    x = np.linspace(0, L, N)

    # --- Initial Conditions (Dam-Break Scenario) ---
    # h: Fluid height (depth)
    # u: Fluid velocity
    h = np.zeros(N)
    u = np.zeros(N)

    # Set up a high water column on the left and low on the right
    h[:N//2] = 2.0     # High water (upstream)
    h[N//2:] = 1.0     # Low water (downstream)

    # --- Numerical Scheme (Lax-Friedrichs) ---
    def step_lax_friedrichs(h, u, dt, dx, g):
        """
        Advances the 1D shallow water equations by one time step
        using the Lax-Friedrichs scheme to maintain numerical stability.
        """
        h_next = h.copy()
        u_next = u.copy()

        # Compute fluxes
        # Mass flux (q = h * u)
        q = h * u
        # Momentum flux
        f_momentum = h * (u**2) + 0.5 * g * (h**2)

        # Internal updates (excluding boundaries)
        for i in range(1, N - 1):
            # Update fluid height (Continuity Equation)
            h_next[i] = 0.5 * (h[i+1] + h[i-1]) - (dt / (2 * dx)) * (q[i+1] - q[i-1])

            # Update momentum (q_next) and extract velocity (u_next)
            q_next = 0.5 * (q[i+1] + q[i-1]) - (dt / (2 * dx)) * (f_momentum[i+1] - f_momentum[i-1])
            u_next[i] = q_next / h_next[i] if h_next[i] > 1e-4 else 0.0

        # Reflective Boundary Conditions
        u_next[0], u_next[-1] = 0.0, 0.0
        h_next[0], h_next[-1] = h_next[1], h_next[-2]

        return h_next, u_next

    # 原本在動畫的 update 裡一格算一步；這裡先算完，第 k 格畫第 k+1 步
    hs, us = [h], [u]
    for _ in range(num_steps):
        h, u = step_lax_friedrichs(h, u, dt, dx, g)
        hs.append(h)
        us.append(u)
    return {"kind": "1d", "N": N, "L": L, "dx": dx, "dt": dt, "num_steps": num_steps,
            "x": x, "h": np.array(hs), "u": np.array(us)}


def _case2():
    """舊格式的 HK6_RUN_CASE2：二維淺水方程、高斯水滴，Arakawa C 網格。
    原本的 global eta, u, v 收進 run：eta 每一格都留，u、v 留最後的。"""
    # =============================================================================
    # 1. PHYSICAL & NUMERICAL PARAMETERS
    # =============================================================================
    L_x = 1.0           # Domain length in x direction (meters)
    L_y = 1.0           # Domain length in y direction (meters)
    Nx = 100            # Number of grid points in x
    Ny = 100            # Number of grid points in y

    dx = L_x / Nx
    dy = L_y / Ny

    g = 9.81            # Acceleration due to gravity (m/s^2)
    H = 0.1             # Mean/undisturbed water depth (meters)

    # CFL Condition for stability: dt < dx / sqrt(2 * g * H)
    c = np.sqrt(g * H)
    dt = 0.4 * min(dx, dy) / c
    n_steps = 400       # Total number of time steps

    # =============================================================================
    # 2. INITIALIZE ARRAYS (Arakawa C-Grid)
    # =============================================================================
    # η (eta) sits at cell centers
    eta = np.zeros((Nx, Ny))

    # u (velocity in x) sits at western/eastern faces
    u = np.zeros((Nx + 1, Ny))

    # v (velocity in y) sits at southern/northern faces
    v = np.zeros((Nx, Ny + 1))

    # Initial condition: A Gaussian droplet in the center of the domain
    x0, y0 = L_x / 2, L_y / 2
    sigma = 0.05
    amplitude = 0.02

    for i in range(Nx):
        for j in range(Ny):
            x = (i + 0.5) * dx
            y = (j + 0.5) * dy
            eta[i, j] = amplitude * np.exp(-((x - x0)**2 + (y - y0)**2) / (2 * sigma**2))

    # =============================================================================
    # 3. SOLVER STEP FUNCTION
    # =============================================================================
    def update_sw_2d(eta, u, v, dt, dx, dy, g, H):
        """
        Updates the 2D shallow water equations for one time step.
        Implements reflective boundary conditions.
        """
        # --- Step 1: Update Velocities (Momentum Equations) ---
        # u_t = -g * eta_x
        u[1:-1, :] -= (dt * g / dx) * (eta[1:, :] - eta[:-1, :])
        # v_t = -g * eta_y
        v[:, 1:-1] -= (dt * g / dy) * (eta[:, 1:] - eta[:, :-1])

        # Boundary Conditions for Velocity (No-slip / Reflective Walls)
        u[0, :] = 0.0
        u[-1, :] = 0.0
        v[:, 0] = 0.0
        v[:, -1] = 0.0

        # --- Step 2: Update Water Height (Continuity Equation) ---
        # eta_t = -H * (u_x + v_y)
        eta -= (dt * H / dx) * (u[1:, :] - u[:-1, :]) + (dt * H / dy) * (v[:, 1:] - v[:, :-1])

        return eta, u, v

    # 原本在動畫的 animate 裡一格算兩步；這裡先算完（陣列是原地改的，所以每格存一份 copy），第 k 格畫 etas[k+1]
    etas = [eta.copy()]
    for _frame in range(n_steps // 2):
        # Advance the simulation by 2 steps per frame to speed up the animation
        for _ in range(2):
            eta, u, v = update_sw_2d(eta, u, v, dt, dx, dy, g, H)
        etas.append(eta.copy())
    return {"kind": "2d", "Nx": Nx, "Ny": Ny, "dx": dx, "dy": dy, "dt": dt, "n_steps": n_steps,
            "amplitude": amplitude, "eta": np.array(etas), "u": u, "v": v}


def compute(case):
    """算。兩個 case 是兩個不同的模擬（1D、2D），各照舊格式的 HK6_RUN_CASE1、HK6_RUN_CASE2。"""
    return {"case-1": _case1, "case-2": _case2}[case]()


def _draw_1d(fig, run):
    x, L = run["x"], run["L"]
    ax1 = fig.add_subplot(2, 1, 1)
    ax2 = fig.add_subplot(2, 1, 2)

    # Plot lines
    line_h, = ax1.plot(x, run["h"][0], color='dodgerblue', lw=2)
    line_u, = ax2.plot(x, run["u"][0], color='crimson', lw=2)

    # Axis styling
    ax1.set_xlim(0, L)
    ax1.set_ylim(0, 2.5)
    ax1.set_ylabel('Water Height ($h$)')
    ax1.set_title('1D Shallow Water Equations Simulation (Dam Break)')

    ax2.set_xlim(0, L)
    ax2.set_ylim(-1, 3)
    ax2.set_xlabel('Position ($x$)')
    ax2.set_ylabel('Velocity ($u$)')

    def update(frame):
        line_h.set_ydata(run["h"][frame + 1])
        line_u.set_ydata(run["u"][frame + 1])
        return line_h, line_u

    ani = FuncAnimation(fig, update, frames=run["num_steps"], interval=20, blit=True)
    fig.tight_layout()
    return ani


def _draw_2d(fig, run):
    Nx, Ny, dx, dy = run["Nx"], run["Ny"], run["dx"], run["dy"]
    amplitude = run["amplitude"]
    ax = fig.add_subplot(111)

    # Create coordinate grids for visualization
    X, Y = np.meshgrid(np.arange(Nx) * dx, np.arange(Ny) * dy, indexing='ij')

    # Plot initial state
    im = ax.pcolormesh(X, Y, run["eta"][0], cmap='RdBu', vmin=-amplitude, vmax=amplitude, shading='auto')
    fig.colorbar(im, ax=ax, label=r'Surface Elevation $\eta$ (m)')
    ax.set_title("2D Shallow Water Equations (Wave Propagation)")
    ax.set_xlabel("X (meters)")
    ax.set_ylabel("Y (meters)")

    def animate(frame):
        im.set_array(run["eta"][frame + 1].ravel())
        return [im]

    return FuncAnimation(fig, animate, frames=run["n_steps"] // 2, interval=20, blit=True)


def draw(fig, run):
    """畫。case-1 上下兩張（h、u），case-2 一張 η 的色圖；都是動畫。"""
    return _draw_1d(fig, run) if run["kind"] == "1d" else _draw_2d(fig, run)


def stats(run):
    if run["kind"] == "1d":
        h = run["h"][-1]
        return [("格點 N", str(run["N"])), ("dx", f"{run['dx']:.4f}"), ("dt", f"{run['dt']:g}"),
                ("步數", str(run["num_steps"])), ("最後 h 範圍", f"{h.min():.3f} ～ {h.max():.3f}")]
    eta = run["eta"][-1]
    return [("格點", f"{run['Nx']} × {run['Ny']}"), ("dx", f"{run['dx']:g}"), ("dt", f"{run['dt']:.5f}"),
            ("步數", str(run["n_steps"])), ("最後 η 範圍", f"{eta.min():.4f} ～ {eta.max():.4f}")]


# ── 以下不用改 ──
HOMEWORK = dict(name=NAME, docs=DOCS, note=NOTE, cases=CASES, compute=compute, draw=draw, stats=stats, file=__file__)
if __name__ == "__main__":
    raise SystemExit(coursework.main(HOMEWORK))
