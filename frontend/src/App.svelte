<script>
  let session = null;
  let logs = [];
  let meters = [];
  let events = [];
  let loginUser = "surveyor";
  let loginPass = "surv123456";
  let chainage = "";
  let deltaMm = "";
  let meterCode = "";
  let blockedCode = "";
  let error = "";
  let notice = "";
  let loading = false;
  let timer;
  let tab = "logs"; // logs=报送页，expiry=到期专页
  // 每号一行的到期日输入框：expiryDraft[code]
  let expiryDrafts = {};

  $: isWriter = session?.role === "writer";
  $: meterMap = Object.fromEntries(meters.map((m) => [m.code, m]));
  $: expiredCount = meters.filter((m) => m.is_expired).length;

  function headers() {
    return session ? { Authorization: "Bearer " + session.token } : {};
  }

  async function refresh() {
    if (!session) return;
    const [lr, mr, er] = await Promise.all([
      fetch("/api/logs", { headers: headers() }),
      fetch("/api/meters", { headers: headers() }),
      fetch("/api/calibration-events", { headers: headers() }),
    ]);
    if (lr.status === 401 || mr.status === 401) {
      logout();
      return;
    }
    if (lr.ok) logs = await lr.json();
    if (mr.ok) {
      meters = await mr.json();
      if (!meterCode && meters.length) meterCode = meters[0].code;
    }
    if (er.ok) events = await er.json();
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
    events = [];
    localStorage.removeItem("tunnel_session");
  }

  async function submit() {
    error = "";
    notice = "";
    blockedCode = "";
    loading = true;
    try {
      const res = await fetch("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ meter_code: meterCode, chainage, delta_mm: Number(deltaMm) }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "提交失败";
        if (data.code === "meter_expired") blockedCode = data.meter?.code || meterCode;
        return;
      }
      chainage = "";
      deltaMm = "";
      notice = "已收下，进入待认领队列";
      await refresh();
    } catch {
      error = "提交时网络异常";
    } finally {
      loading = false;
    }
  }

  async function changeExpiry(code) {
    error = "";
    notice = "";
    const expires_on = (expiryDrafts[code] || "").trim();
    if (!expires_on) {
      error = `请先为 ${code} 填写新的到期日`;
      return;
    }
    loading = true;
    try {
      const res = await fetch(`/api/meters/${encodeURIComponent(code)}/expiry`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...headers() },
        body: JSON.stringify({ expires_on }),
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "改期失败";
        return;
      }
      notice = `${code} 到期日已改为 ${expires_on}`;
      expiryDrafts[code] = "";
      await refresh();
    } finally {
      loading = false;
    }
  }

  async function renew(code) {
    error = "";
    notice = "";
    loading = true;
    try {
      const res = await fetch(`/api/meters/${encodeURIComponent(code)}/renew`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...headers() },
        body: "{}",
      });
      const data = await res.json();
      if (!res.ok) {
        error = data.detail || "续期失败";
        return;
      }
      notice = `${code} 已续期至 ${data.meter.expires_on}，可重新报送`;
      await refresh();
    } finally {
      loading = false;
    }
  }

  function goRenew(code) {
    tab = "expiry";
    error = "";
    // 到期专页打开后点该号的续期即可；这里给出提示
    notice = `请在下方为 ${code} 办理续期，续期后再开报送`;
  }

  function eventKindText(k) {
    return { renew: "续期", expiry_change: "改到期日", register: "登记建档" }[k] || k;
  }

  function fmtTime(iso) {
    if (!iso) return "—";
    return iso.replace("T", " ").slice(0, 19) + " UTC";
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
  .topbar {
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #44403c; padding-bottom: 0.75rem; margin-bottom: 1rem;
  }
  h1 { color: #fbbf24; margin: 0; font-size: 1.25rem; }
  .tabs { display: flex; gap: 0.5rem; }
  .tab {
    cursor: pointer; padding: 0.4rem 0.9rem; border-radius: 6px;
    background: #292524; border: 1px solid #44403c; color: #d6d3d1; font-weight: 600;
  }
  .tab.active { background: #d97706; border-color: #d97706; color: #fff; }
  .tab .dot { color: #fca5a5; margin-left: 0.35rem; }
  .sub { color: #a8a29e; margin-bottom: 1.25rem; }
  section {
    background: #292524; border: 1px solid #44403c; border-radius: 8px;
    padding: 1rem 1.25rem; margin-bottom: 1rem;
  }
  label { display: block; font-size: 0.85rem; color: #d6d3d1; margin-bottom: 0.25rem; }
  input, select {
    width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px;
    border: 1px solid #57534e; background: #0c0a09; color: #fafaf9; margin-bottom: 0.75rem;
  }
  input.inline, .inline-wrap input { width: auto; margin-bottom: 0; min-width: 150px; }
  button {
    cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px;
    background: #d97706; color: #fff; font-weight: 600;
  }
  button.secondary { background: #57534e; }
  button.small { padding: 0.3rem 0.7rem; font-size: 0.82rem; }
  .err { color: #fb7185; }
  .ok-msg { color: #86efac; }
  .blockbox {
    margin-top: 0.5rem; padding: 0.6rem 0.8rem; border-radius: 6px;
    background: #7f1d1d; color: #fecaca; border: 1px solid #b91c1c;
  }
  .blockbox button { margin-top: 0.5rem; background: #b91c1c; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
  th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #44403c; vertical-align: top; }
  .tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; white-space: nowrap; }
  .ok { background: #14532d; color: #86efac; }
  .bad { background: #7f1d1d; color: #fca5a5; }
  .pending { background: #713f12; color: #fde68a; }
  .blocked { background: #450a0a; color: #fca5a5; }
  .muted { color: #a8a29e; font-size: 0.8rem; }
  .who { color: #d6d3d1; font-size: 0.85rem; }
  .inline-wrap { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
</style>

<main>
  {#if !session}
    <h1>隧道收敛测缝台</h1>
    <p class="sub">测量员提交桩号与收敛毫米值，接口进程内线程认领后出结论。登录框已预填可写账号 surveyor / surv123456。</p>
    <section>
      <label>用户名</label>
      <input bind:value={loginUser} autocomplete="off" />
      <label>密码</label>
      <input type="password" bind:value={loginPass} autocomplete="off" />
      <button disabled={loading} on:click={login}>登录</button>
      {#if error}<p class="err">{error}</p>{/if}
    </section>
  {:else}
    <div class="topbar">
      <h1>隧道收敛测缝台</h1>
      <div class="tabs">
        <div class="tab {tab === 'logs' ? 'active' : ''}" on:click={() => (tab = "logs")}
             on:keydown={() => {}} role="button">收敛报送</div>
        <div class="tab {tab === 'expiry' ? 'active' : ''}" on:click={() => (tab = "expiry")}
             on:keydown={() => {}} role="button">
          校准到期专页{#if expiredCount > 0}<span class="dot">● {expiredCount} 号已过期</span>{/if}
        </div>
      </div>
    </div>

    <section>
      <span class="who">已登录：{session.username}（{isWriter ? "测量员 · 可提交" : "巡检员 · 只读"}）</span>
      &nbsp;
      <button class="secondary small" on:click={logout}>退出</button>
      <button class="secondary small" disabled={loading} on:click={refresh}>刷新</button>
    </section>

    {#if error}<p class="err">{error}</p>{/if}
    {#if notice}<p class="ok-msg">{notice}</p>{/if}

    {#if tab === "logs"}
      {#if isWriter}
        <section>
          <label>测缝计号</label>
          <select bind:value={meterCode}>
            {#each meters as m}
              <option value={m.code}>
                {m.code} {m.label}（{m.is_expired ? "校准已过期 " + m.expires_on : "有效至 " + m.expires_on}）
              </option>
            {/each}
          </select>
          <label>里程桩号</label>
          <input placeholder="例如 K20+050" bind:value={chainage} />
          <label>收敛（毫米，可正可负）</label>
          <input type="number" step="0.1" bind:value={deltaMm} />
          <button disabled={loading} on:click={submit}>提交（进入待认领）</button>
          {#if blockedCode}
            <div class="blockbox">
              该号校准已过期，本次读数未被收下。请先办理续期，续期以后再开报送。
              <div>
                <button class="small" on:click={() => goRenew(blockedCode)}>去为 {blockedCode} 续期</button>
              </div>
            </div>
          {/if}
        </section>
      {/if}

      <section>
        <table>
          <thead>
            <tr><th>编号</th><th>测缝计号</th><th>桩号</th><th>收敛mm</th><th>状态</th><th>结论</th><th>说明</th></tr>
          </thead>
          <tbody>
            {#each logs as row}
              <tr>
                <td>{row.id}</td>
                <td>{row.meter_code ?? "—"}</td>
                <td>{row.chainage}</td>
                <td>{row.delta_mm}</td>
                <td>
                  {#if row.status === 'pending'}
                    <span class="tag pending">待处理</span>
                  {:else if row.status === 'blocked'}
                    <span class="tag blocked">校准过期·拦住</span>
                  {:else}
                    <span class="tag ok">已完成</span>
                  {/if}
                </td>
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
      <p class="sub">各测缝计校准到期日与最近一次拦住原因。{isWriter ? "测量员可改到期日、办理续期。" : "巡检员只读。"}</p>
      <section>
        <table>
          <thead>
            <tr>
              <th>测缝计号</th><th>名称</th><th>校准到期日</th><th>状态</th>
              <th>最近拦住的原因</th>{#if isWriter}<th>操作（测量员）</th>{/if}
            </tr>
          </thead>
          <tbody>
            {#each meters as m}
              <tr>
                <td><strong>{m.code}</strong></td>
                <td>{m.label}</td>
                <td>{m.expires_on}</td>
                <td>
                  {#if m.is_expired}
                    <span class="tag bad">已过期</span>
                  {:else}
                    <span class="tag ok">有效</span>
                  {/if}
                </td>
                <td>
                  {#if m.last_block_reason}
                    {m.last_block_reason}
                    <div class="muted">拦住时间：{fmtTime(m.last_block_at)}</div>
                  {:else}
                    <span class="muted">尚未被拦</span>
                  {/if}
                </td>
                {#if isWriter}
                  <td>
                    <div class="inline-wrap">
                      <input class="inline" type="date" bind:value={expiryDrafts[m.code]} />
                      <button class="small secondary" disabled={loading || !expiryDrafts[m.code]}
                              on:click={() => changeExpiry(m.code)}>改到期日</button>
                      <button class="small" disabled={loading} on:click={() => renew(m.code)}>续期一年</button>
                    </div>
                    <div class="muted">可把到期日改到昨天：一改过期，该号再报即被拦。</div>
                  </td>
                {/if}
              </tr>
            {/each}
          </tbody>
        </table>
      </section>

      <section>
        <h3 style="margin:0 0 0.5rem;color:#fbbf24;">续期 / 改期痕迹</h3>
        <table>
          <thead>
            <tr><th>时间</th><th>测缝计号</th><th>类型</th><th>原到期日</th><th>新到期日</th><th>操作人</th></tr>
          </thead>
          <tbody>
            {#each events as ev}
              <tr>
                <td class="muted">{fmtTime(ev.created_at)}</td>
                <td>{ev.meter_code}</td>
                <td>
                  <span class="tag {ev.kind === 'renew' ? 'ok' : ev.kind === 'expiry_change' ? 'pending' : ''}">
                    {eventKindText(ev.kind)}
                  </span>
                </td>
                <td>{ev.old_expires_on ?? "—"}</td>
                <td>{ev.new_expires_on}</td>
                <td>{ev.actor}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </section>
    {/if}
  {/if}
</main>
