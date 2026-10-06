<script>
  let session = null;
  let view = "logs"; // logs | meters
  let logs = [];
  let meters = [];
  let loginUser = "surveyor";
  let loginPass = "surv123456";
  let meterNo = "甲";
  let chainage = "";
  let deltaMm = "";
  // 到期专页每行一个编辑框：draft[号] = 日期串
  let draft = {};
  let error = "";
  let notice = "";
  let loading = false;
  let timer;

  $: isWriter = session?.role === "writer";

  function headers() {
    return session ? { Authorization: "Bearer " + session.token } : {};
  }

  function fmtDate(iso) {
    return iso ? iso.slice(0, 10) : "—";
  }
  function fmtTime(iso) {
    return iso ? iso.replace("T", " ").slice(0, 19) + " UTC" : "—";
  }

  async function refresh() {
    if (!session) return;
    const opts = { headers: headers() };
    const tasks = [fetch("/api/logs", opts)];
    if (view === "meters") tasks.push(fetch("/api/meters", opts));
    const [logsRes, metersRes] = await Promise.all(tasks);
    if (logsRes.status === 401) {
      logout();
      return;
    }
    if (logsRes.ok) logs = await logsRes.json();
    if (metersRes && metersRes.ok) meters = await metersRes.json();
  }

  async function login() {
    error = "";
    loading = true;
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUser, password: loginPass }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "登录失败";
        return;
      }
      session = { token: data.access_token, username: data.username, role: data.role };
      localStorage.setItem("tunnel_session", JSON.stringify(session));
      await refresh();
      timer = setInterval(refresh, 2000);
    } catch {
      error = "无法连接接口";
    } finally {
      loading = false;
    }
  }

  function logout() {
    if (timer) clearInterval(timer);
    session = null;
    logs = [];
    meters = [];
    localStorage.removeItem("tunnel_session");
  }

  async function switchView(name) {
    view = name;
    error = "";
    notice = "";
    await refresh();
  }

  async function submit() {
    error = "";
    notice = "";
    loading = true;
    try {
      const res = await fetch("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ meter_no: meterNo, chainage, delta_mm: Number(deltaMm) }),
      });
      const data = await res.json();
      if (!res.ok) {
        // 过期被拦：明确提示先续期，并自动切到到期专页方便办理
        error = data.detail || "提交失败";
        if (data.code === "calibration_expired") {
          draft[data.meter_no] = "";
          setTimeout(() => switchView("meters"), 600);
        }
        return;
      }
      chainage = "";
      deltaMm = "";
      notice = `已收下（编号 ${data.id}），等待认领判定`;
      await refresh();
    } catch {
      error = "提交时网络异常";
    } finally {
      loading = false;
    }
  }

  async function renew(no) {
    error = "";
    notice = "";
    const value = (draft[no] || "").trim();
    if (!value) {
      error = `请先为测缝计 ${no} 选择新的到期日`;
      return;
    }
    loading = true;
    try {
      const res = await fetch(`/api/meters/${encodeURIComponent(no)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ calibrated_until: value }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "续期失败";
        return;
      }
      draft[no] = "";
      notice = `测缝计 ${no} 到期日已改为 ${value}，可以重新报送`;
      await refresh();
    } catch {
      error = "续期时网络异常";
    } finally {
      loading = false;
    }
  }

  const raw = localStorage.getItem("tunnel_session");
  if (raw) {
    try {
      session = JSON.parse(raw);
      refresh();
      timer = setInterval(refresh, 2000);
    } catch {
      localStorage.removeItem("tunnel_session");
    }
  }
</script>

<style>
  :global(body) {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: #1c1917;
    color: #f5f5f4;
  }
  main { max-width: 1040px; margin: 0 auto; padding: 1.5rem; }
  header {
    display: flex; align-items: center; gap: 1rem; flex-wrap: wrap;
    border-bottom: 1px solid #44403c; padding-bottom: 0.75rem; margin-bottom: 1rem;
  }
  h1 { color: #fbbf24; margin: 0; font-size: 1.3rem; }
  nav { display: flex; gap: 0.5rem; }
  nav a {
    cursor: pointer; color: #d6d3d1; text-decoration: none;
    padding: 0.3rem 0.7rem; border-radius: 6px; border: 1px solid #57534e;
    font-size: 0.9rem;
  }
  nav a.active { background: #d97706; color: #fff; border-color: #d97706; }
  .spacer { flex: 1; }
  .sub { color: #a8a29e; margin-bottom: 1rem; }
  section {
    background: #292524; border: 1px solid #44403c; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
  }
  label { display: block; font-size: 0.85rem; color: #d6d3d1; margin-bottom: 0.25rem; }
  input {
    box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px;
    border: 1px solid #57534e; background: #0c0a09; color: #fafaf9; margin-bottom: 0.75rem;
  }
  input.full { width: 100%; }
  input.date { width: 150px; margin-bottom: 0; }
  button {
    cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px;
    background: #d97706; color: #fff; font-weight: 600;
  }
  button.secondary { background: #57534e; }
  .err { color: #fb7185; }
  .ok-msg { color: #86efac; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
  th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #44403c; vertical-align: top; }
  .tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; white-space: nowrap; }
  .ok { background: #14532d; color: #86efac; }
  .bad { background: #7f1d1d; color: #fca5a5; }
  .pending { background: #713f12; color: #fde68a; }
  .muted { color: #a8a29e; font-size: 0.8rem; }
  .renew-row { display: flex; gap: 0.5rem; align-items: center; }
</style>

<main>
  {#if !session}
    <h1>隧道收敛测缝台</h1>
    <p class="sub">测量员提交测缝计号、桩号与收敛毫米值，接口进程内线程认领后出结论。校准过期的测缝计不许报送，先续期再开报。登录框已预填可写账号 surveyor / surv123456（只读账号 inspector / insp123456）。</p>
    <section>
      <label>用户名</label>
      <input class="full" bind:value={loginUser} autocomplete="off" />
      <label>密码</label>
      <input class="full" type="password" bind:value={loginPass} autocomplete="off" />
      <button disabled={loading} on:click={login}>登录</button>
      {#if error}<p class="err">{error}</p>{/if}
    </section>
  {:else}
    <header>
      <h1>隧道收敛测缝台</h1>
      <nav>
        <a class:active={view === "logs"} on:click={() => switchView("logs")}>报送台</a>
        <a class:active={view === "meters"} on:click={() => switchView("meters")}>校准到期专页</a>
      </nav>
      <span class="spacer"></span>
      <span class="muted">{session.username}（{isWriter ? "可提交" : "只读"}）</span>
      <button class="secondary" on:click={logout}>退出</button>
    </header>

    {#if error}<p class="err">{error}</p>{/if}
    {#if notice}<p class="ok-msg">{notice}</p>{/if}

    {#if view === "logs"}
      {#if isWriter}
        <section>
          <label>测缝计号（铭牌）</label>
          <input class="full" placeholder="例如 甲" bind:value={meterNo} />
          <label>里程桩号</label>
          <input class="full" placeholder="例如 K20+050" bind:value={chainage} />
          <label>收敛（毫米，可正可负）</label>
          <input class="full" type="number" step="0.1" bind:value={deltaMm} />
          <button disabled={loading} on:click={submit}>报送（进入待认领）</button>
        </section>
      {:else}
        <p class="sub">巡检员只读：不能报送，也不能修改校准到期日。</p>
      {/if}
      <section>
        <table>
          <thead>
            <tr><th>编号</th><th>测缝计</th><th>桩号</th><th>收敛mm</th><th>状态</th><th>结论</th><th>说明</th></tr>
          </thead>
          <tbody>
            {#each logs as row}
              <tr>
                <td>{row.id}</td>
                <td>{row.meter_no ?? "—"}</td>
                <td>{row.chainage}</td>
                <td>{row.delta_mm}</td>
                <td><span class="tag {row.status === 'pending' ? 'pending' : 'ok'}">{row.status === 'pending' ? '待处理' : '已完成'}</span></td>
                <td>
                  {#if row.verdict}
                    <span class="tag {row.verdict === '合格' ? 'ok' : 'bad'}">{row.verdict}</span>
                  {:else}—{/if}
                </td>
                <td>{row.reason ?? "—"}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {:else}
      <p class="sub">各测缝计的校准有效期与最近一次拦住原因。{isWriter ? "过期后先在此续期，再回报送台开报。" : "只读视图。"}</p>
      <section>
        <table>
          <thead>
            <tr>
              <th>测缝计</th><th>校准到期日</th><th>状态</th>
              <th>最近拦住的原因</th><th>最近续期</th>
              {#if isWriter}<th>办理续期 / 改期</th>{/if}
            </tr>
          </thead>
          <tbody>
            {#each meters as m}
              <tr>
                <td><strong>{m.meter_no}</strong></td>
                <td>{fmtDate(m.calibrated_until)}</td>
                <td>
                  {#if m.expired}
                    <span class="tag bad">已过期 · 禁止报送</span>
                  {:else}
                    <span class="tag ok">有效期内</span>
                  {/if}
                </td>
                <td>
                  {#if m.latest_block}
                    {m.latest_block.reason}
                    <div class="muted">桩号 {m.latest_block.chainage ?? "—"} · {m.latest_block.blocked_by} · {fmtTime(m.latest_block.blocked_at)}</div>
                  {:else}<span class="muted">无</span>{/if}
                </td>
                <td>
                  {#if m.latest_renewal}
                    {fmtDate(m.latest_renewal.old_until)} → {fmtDate(m.latest_renewal.new_until)}
                    <div class="muted">{m.latest_renewal.changed_by} · {fmtTime(m.latest_renewal.changed_at)}</div>
                  {:else}<span class="muted">未续期过</span>{/if}
                </td>
                {#if isWriter}
                  <td>
                    <div class="renew-row">
                      <input class="date" type="date" bind:value={draft[m.meter_no]} />
                      <button disabled={loading} on:click={() => renew(m.meter_no)}>续期</button>
                    </div>
                    <div class="muted">改到期日即留痕，过期号立即恢复报送</div>
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}
  {/if}
</main>
