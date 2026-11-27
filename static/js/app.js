        const pad2 = (n) => String(n).padStart(2, '0');
        const localYM = (date = new Date()) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
        const localYMD = (date = new Date()) => `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
        const isDarkTheme = () => document.documentElement.classList.contains('dark');
        const chartColors = () => isDarkTheme() ? '#a1a1aa' : '#71717a';
        const escAttr = (s = '') => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        const escHtml = (s = '') => String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
        const escJs = (s = '') => JSON.stringify(String(s == null ? '' : s))
            .replace(/</g, '\\u003c')
            .replace(/>/g, '\\u003e')
            .replace(/&/g, '\\u0026')
            .replace(/'/g, '\\u0027');
        // For values interpolated inside an inline handler attribute such as
        // onclick="fn(<HERE>)". The value is first JSON-encoded for JavaScript,
        // then the whole result is HTML-attribute-encoded exactly once so that
        // the attribute parser restores the JSON string and the JS parser
        // restores the original value.
        const escHandlerArg = (s = '') => escAttr(escJs(s));
        const savedTheme = (() => { try { return localStorage.getItem('theme'); } catch (e) { return null; } })();
        const VALID_VIEWS = new Set(['dashboard', 'income', 'expenses', 'jobs', 'targets', 'summary', 'admin', 'profile']);
        const activeCharts = new Map();

        function destroyAllCharts() {
            for (const chart of activeCharts.values()) {
                try { chart.destroy(); } catch (e) {}
            }
            activeCharts.clear();
        }

        function createChart(canvasId, config) {
            const canvas = document.getElementById(canvasId);
            if (!canvas) return null;
            const prev = activeCharts.get(canvasId);
            if (prev) {
                try { prev.destroy(); } catch (e) {}
                activeCharts.delete(canvasId);
            }
            const chart = new Chart(canvas, config);
            activeCharts.set(canvasId, chart);
            return chart;
        }

        function resolveView(view) {
            if (view === 'notes') return 'notes';
            if (!VALID_VIEWS.has(view)) return 'dashboard';
            if (view === 'admin' && (!state.user || state.user.role !== 'admin')) return 'dashboard';
            return view;
        }

        function viewToUrl(view) {
            return view === 'dashboard' ? '/' : `/?view=${encodeURIComponent(view)}`;
        }

        function getMonthDayStats(ym) {
            const [year, month] = ym.split('-').map(Number);
            const daysInMonth = new Date(year, month, 0).getDate();
            const monthName = new Date(year, month - 1).toLocaleString('default', { month: 'long', year: 'numeric' });
            const todayYM = localYM();
            if (ym === todayYM) {
                const daysElapsed = new Date().getDate();
                return { divisor: daysElapsed, label: `the last ${daysElapsed} days of this month` };
            }
            if (ym < todayYM) {
                return { divisor: daysInMonth, label: `all ${daysInMonth} days of ${monthName}` };
            }
            return { divisor: daysInMonth, label: `${monthName} (${daysInMonth} days)` };
        }

        function getWeeklyWindowForMonth(ym) {
            const [year, month] = ym.split('-').map(Number);
            const daysInMonth = new Date(year, month, 0).getDate();
            const todayYM = localYM();
            if (ym === todayYM) {
                const days = [...Array(7)].map((_, i) => {
                    const d = new Date();
                    d.setDate(d.getDate() - i);
                    return localYMD(d);
                }).reverse();
                return { days, subtitle: 'Last 7 days' };
            }
            if (ym < todayYM) {
                const startDay = Math.max(1, daysInMonth - 6);
                const days = [];
                for (let day = startDay; day <= daysInMonth; day++) {
                    days.push(`${year}-${pad2(month)}-${pad2(day)}`);
                }
                return { days, subtitle: `Last 7 days of ${ym}` };
            }
            const days = [];
            for (let day = 1; day <= Math.min(7, daysInMonth); day++) {
                days.push(`${year}-${pad2(month)}-${pad2(day)}`);
            }
            return { days, subtitle: `First 7 days of ${ym}` };
        }

        function closeActiveModal() {
            const modal = document.getElementById('modal-container');
            if (modal && modal.innerHTML) modal.innerHTML = '';
            const expModal = document.getElementById('expense-modal-container');
            if (expModal && expModal.innerHTML) expModal.innerHTML = '';
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') closeActiveModal();
        });

        window.addEventListener('popstate', (event) => {
            if (!state.user) return;
            const raw = (event.state && event.state.view) || new URLSearchParams(window.location.search).get('view') || 'dashboard';
            const resolved = resolveView(raw);
            if (resolved === 'notes') {
                window.location.href = '/notes';
                return;
            }
            state.currentView = resolved;
            state.mobileMenuOpen = false;
            render();
        });

        // Basic SPA Router and State Management
        let state = {
            user: null,
            jobs: [],
            income: [],
            targets: [],
            expenses: [],
            expenseBudgets: [],
            currentView: 'dashboard',
            authView: 'login',
            loading: true,
            mobileMenuOpen: false,
            selectedMonth: localYM(),
            expenseStats: null,
            theme: (savedTheme === 'dark' ? 'dark' : 'light'),
            forgotUsername: null
        };

        function showToast(message, type = 'success') {
            const toast = document.getElementById('toast');
            if (!toast) return;
            toast.textContent = message;
            toast.className = 'toast ' + type + ' show';
            setTimeout(() => toast.classList.remove('show'), 3000);
        }

        async function init() {
            try {
                const res = await fetch('/api/auth/me');
                state.user = res.ok ? await res.json() : null;
                if (state.user) {
                    await fetchData();
                    const viewParam = new URLSearchParams(window.location.search).get('view');
                    if (viewParam === 'notes') {
                        window.location.replace('/notes');
                        return;
                    }
                    state.currentView = resolveView(viewParam || 'dashboard');
                    window.history.replaceState({ view: state.currentView }, '', viewToUrl(state.currentView));
                }
            } catch (e) {
                state.user = null;
                showToast('Unable to connect to server', 'error');
            }
            state.loading = false;
            render();
        }

        async function fetchStats() {
            const month = state.selectedMonth;
            try {
                const res = await fetch(`/api/expenses/stats?month=${month}`);
                const data = res.ok ? await res.json() : null;
                if (state.selectedMonth === month) state.expenseStats = data;
            } catch (e) {
                if (state.selectedMonth === month) state.expenseStats = null;
            }
        }

        async function fetchData() {
            const [jobsRes, incomeRes, targetsRes, expensesRes, budgetsRes] = await Promise.all([
                fetch('/api/jobs'),
                fetch('/api/income'),
                fetch('/api/targets'),
                fetch('/api/expenses'),
                fetch('/api/expenses/budgets')
            ]);
            state.jobs = await jobsRes.json();
            state.income = await incomeRes.json();
            state.targets = await targetsRes.json();
            state.expenses = expensesRes.ok ? await expensesRes.json() : [];
            state.expenseBudgets = budgetsRes.ok ? await budgetsRes.json() : [];
            await fetchStats();
        }

        function render() {
            const app = document.getElementById('app');
            if (state.loading) {
                app.innerHTML = '<div class="flex items-center justify-center h-screen"><div class="animate-spin rounded-full h-12 w-12 border-b-2 border-zinc-900"></div></div>';
                lucide.createIcons();
                return;
            }

            if (!state.user) {
                if (state.authView === 'login') renderAuth();
                else if (state.authView === 'forgot') renderForgot();
                else if (state.authView === 'reset') renderReset();
                else renderRegister();
                return;
            }

            renderMain();
        }

        function renderAuth(error = null) {
            const app = document.getElementById('app');
            app.innerHTML = `
                <div class="min-h-screen flex items-center justify-center p-4">
                    <div class="max-w-md w-full animate-slide">
                        <div class="bg-white p-10 rounded-[2.5rem] card-shadow border border-black/5 relative overflow-hidden">
                            <div class="absolute top-0 left-0 w-full h-2 bg-zinc-900"></div>
                            <div class="mb-10 text-center">
                                <div class="w-16 h-16 bg-zinc-900 rounded-2xl flex items-center justify-center text-white mx-auto mb-6 shadow-lg rotate-3">
                                    <i data-lucide="wallet" class="w-8 h-8"></i>
                                </div>
                                <h1 class="text-4xl font-extrabold tracking-tight mb-2">Welcome Back</h1>
                                <p class="text-zinc-500 font-medium">Manage your income with precision.</p>
                            </div>
                            
                            ${error ? `
                                <div class="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl flex items-center gap-3 text-red-600 animate-pulse">
                                    <i data-lucide="alert-circle" class="w-5 h-5"></i>
                                    <p class="text-sm font-bold">${escAttr(error)}</p>
                                </div>
                            ` : ''}

                            <form id="loginForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Username</label>
                                    <input type="text" id="username" name="username" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Enter your username" required>
                                </div>
                                <div>
                                    <div class="flex justify-between items-center mb-2">
                                        <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 ml-1">Password</label>
                                        <a href="#" id="showForgot" class="text-[11px] font-bold text-zinc-400 hover:text-zinc-900 transition-colors">Forgot password?</a>
                                    </div>
                                    <input type="password" id="password" name="password" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="••••••••" required>
                                </div>
                                <button type="submit" class="w-full py-5 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-xl shadow-zinc-200 flex items-center justify-center gap-2 group">
                                    <span>Sign In</span>
                                    <i data-lucide="arrow-right" class="w-5 h-5 group-hover:translate-x-1 transition-transform"></i>
                                </button>
                            </form>
                            
                            <div class="mt-10 pt-8 border-t border-zinc-100 text-center">
                                <p class="text-sm text-zinc-500 font-medium">
                                    New here? <a href="#" id="showRegister" class="text-zinc-900 font-bold hover:underline underline-offset-4">Create an account</a>
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('showRegister').onclick = (e) => {
                e.preventDefault();
                state.authView = 'register';
                render();
            };

            document.getElementById('showForgot').onclick = (e) => {
                e.preventDefault();
                state.authView = 'forgot';
                render();
            };

            document.getElementById('loginForm').onsubmit = async (e) => {
                e.preventDefault();
                const username = e.target.username.value;
                const password = e.target.password.value;
                let res;
                try {
                    res = await fetch('/api/auth/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                } catch (err) {
                    renderAuth('Cannot reach the server. Check your connection and try again.');
                    return;
                }
                if (res.ok) {
                    state.user = await res.json();
                    state.currentView = resolveView(state.currentView);
                    window.history.replaceState({ view: state.currentView }, '', viewToUrl(state.currentView));
                    await fetchData();
                    render();
                } else if (res.status === 401) {
                    renderAuth('Invalid credentials. Please re-enter your password.');
                } else {
                    const errBody = await res.json().catch(() => ({}));
                    renderAuth(errBody.error || `Login failed (HTTP ${res.status}). Please try again.`);
                }
            };
        }

        function renderRegister(error = null) {
            const app = document.getElementById('app');
            app.innerHTML = `
                <div class="min-h-screen flex items-center justify-center p-4">
                    <div class="max-w-md w-full animate-slide">
                        <div class="bg-white p-10 rounded-[2.5rem] card-shadow border border-black/5 relative overflow-hidden">
                            <div class="absolute top-0 left-0 w-full h-2 bg-emerald-500"></div>
                            <div class="mb-10 text-center">
                                <div class="w-16 h-16 bg-emerald-500 rounded-2xl flex items-center justify-center text-white mx-auto mb-6 shadow-lg -rotate-3">
                                    <i data-lucide="user-plus" class="w-8 h-8"></i>
                                </div>
                                <h1 class="text-4xl font-extrabold tracking-tight mb-2">Join Us</h1>
                                <p class="text-zinc-500 font-medium">Start tracking your growth today.</p>
                            </div>

                            ${error ? `
                                <div class="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl flex items-center gap-3 text-red-600 animate-pulse">
                                    <i data-lucide="alert-circle" class="w-5 h-5"></i>
                                    <p class="text-sm font-bold">${escAttr(error)}</p>
                                </div>
                            ` : ''}

                            <form id="registerForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Username</label>
                                    <input type="text" id="username" name="username" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Choose a username" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Password</label>
                                    <input type="password" id="password" name="password" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="••••••••" required>
                                </div>
                                <button type="submit" class="w-full py-5 bg-emerald-600 text-white rounded-2xl font-bold hover:bg-emerald-700 transition-all shadow-xl shadow-emerald-100 flex items-center justify-center gap-2 group">
                                    <span>Create Account</span>
                                    <i data-lucide="sparkles" class="w-5 h-5 group-hover:scale-110 transition-transform"></i>
                                </button>
                            </form>
                            
                            <div class="mt-10 pt-8 border-t border-zinc-100 text-center">
                                <p class="text-sm text-zinc-500 font-medium">
                                    Already have an account? <a href="#" id="showLogin" class="text-zinc-900 font-bold hover:underline underline-offset-4">Sign in instead</a>
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('showLogin').onclick = (e) => {
                e.preventDefault();
                state.authView = 'login';
                render();
            };

            document.getElementById('registerForm').onsubmit = async (e) => {
                e.preventDefault();
                const username = e.target.username.value;
                const password = e.target.password.value;
                let res;
                try {
                    res = await fetch('/api/auth/register', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                } catch (err) {
                    renderRegister('Cannot reach the server. Check your connection and try again.');
                    return;
                }
                if (res.ok) {
                    alert('Registration successful! Please login.');
                    state.authView = 'login';
                    render();
                } else {
                    let message = `Registration failed (HTTP ${res.status}). Please try again.`;
                    try {
                        const data = await res.json();
                        if (data && data.error) message = data.error;
                    } catch (err) {}
                    renderRegister(message);
                }
            };
        }

        function renderForgot(error = null, notice = null, prefilledToken = null) {
            const app = document.getElementById('app');
            app.innerHTML = `
                <div class="min-h-screen flex items-center justify-center p-4">
                    <div class="max-w-md w-full animate-slide">
                        <div class="bg-white p-10 rounded-[2.5rem] card-shadow border border-black/5 relative overflow-hidden">
                            <div class="absolute top-0 left-0 w-full h-2 bg-amber-400"></div>
                            <div class="mb-10 text-center">
                                <div class="w-16 h-16 bg-amber-400 rounded-2xl flex items-center justify-center text-white mx-auto mb-6 shadow-lg rotate-3">
                                    <i data-lucide="key-round" class="w-8 h-8"></i>
                                </div>
                                <h1 class="text-4xl font-extrabold tracking-tight mb-2">Forgot Password</h1>
                                <p class="text-zinc-500 font-medium">Request a reset code for your account.</p>
                            </div>

                            ${error ? `
                                <div class="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl flex items-center gap-3 text-red-600 animate-pulse">
                                    <i data-lucide="alert-circle" class="w-5 h-5"></i>
                                    <p class="text-sm font-bold">${escAttr(error)}</p>
                                </div>
                            ` : ''}
                            ${notice ? `
                                <div class="mb-6 p-4 bg-emerald-50 border border-emerald-100 rounded-2xl flex items-start gap-3 text-emerald-600">
                                    <i data-lucide="check-circle-2" class="w-5 h-5 flex-shrink-0"></i>
                                    <p class="text-sm font-bold">${escAttr(notice)}${prefilledToken ? '<br><span class="font-mono font-black select-all">' + escAttr(prefilledToken) + '</span>' : ''}</p>
                                </div>
                            ` : ''}
                            <form id="forgotForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Username</label>
                                    <input type="text" name="username" value="${escAttr(state.forgotUsername || '')}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Enter your username" required>
                                </div>
                                <button type="submit" class="w-full py-5 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-xl shadow-zinc-200 flex items-center justify-center gap-2 group">
                                    <span>Get Reset Code</span>
                                    <i data-lucide="arrow-right" class="w-5 h-5 group-hover:translate-x-1 transition-transform"></i>
                                </button>
                            </form>

                            <div class="mt-4">
                                <button onclick="window.goToReset()" class="w-full py-4 bg-emerald-500 text-white rounded-2xl font-bold hover:bg-emerald-600 transition-all shadow-lg shadow-emerald-100">I have my code — Reset now</button>
                            </div>

                            <div class="mt-10 pt-8 border-t border-zinc-100 text-center">
                                <p class="text-sm text-zinc-500 font-medium">
                                    <a href="#" id="backToLogin" class="text-zinc-900 font-bold hover:underline underline-offset-4">Back to sign in</a>
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('backToLogin').onclick = (e) => {
                e.preventDefault();
                state.authView = 'login';
                render();
            };

            document.getElementById('forgotForm').onsubmit = async (e) => {
                e.preventDefault();
                const username = e.target.username.value.trim();
                const res = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username })
                });
                const data = await res.json();
                if (res.ok) {
                    state.forgotUsername = username;
                    const followUp = data.reset_token ? ' Then press "Reset now".' : ' Once you have the code, press "I have my code — Reset now" below.';
                    renderForgot(null, data.message + followUp, data.reset_token || null);
                } else {
                    renderForgot(data.error || 'Something went wrong. Please try again.');
                }
            };
        }

        function renderReset(error = null) {
            const app = document.getElementById('app');
            app.innerHTML = `
                <div class="min-h-screen flex items-center justify-center p-4">
                    <div class="max-w-md w-full animate-slide">
                        <div class="bg-white p-10 rounded-[2.5rem] card-shadow border border-black/5 relative overflow-hidden">
                            <div class="absolute top-0 left-0 w-full h-2 bg-emerald-500"></div>
                            <div class="mb-10 text-center">
                                <div class="w-16 h-16 bg-zinc-900 rounded-2xl flex items-center justify-center text-white mx-auto mb-6 shadow-lg -rotate-3">
                                    <i data-lucide="lock-keyhole" class="w-8 h-8"></i>
                                </div>
                                <h1 class="text-4xl font-extrabold tracking-tight mb-2">Reset Password</h1>
                                <p class="text-zinc-500 font-medium">Enter your reset code and a new password.</p>
                            </div>

                            ${error ? `
                                <div class="mb-6 p-4 bg-red-50 border border-red-100 rounded-2xl flex items-center gap-3 text-red-600 animate-pulse">
                                    <i data-lucide="alert-circle" class="w-5 h-5"></i>
                                    <p class="text-sm font-bold">${escAttr(error)}</p>
                                </div>
                            ` : ''}

                            <form id="resetForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Username</label>
                                    <input type="text" name="username" value="${escAttr(state.forgotUsername || '')}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Enter your username" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Reset Code</label>
                                    <input type="text" name="token" class="font-mono w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Paste your reset code" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">New Password</label>
                                    <input type="password" name="new_password" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="At least 6 characters" minlength="6" required>
                                </div>
                                <button type="submit" class="w-full py-5 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-xl shadow-zinc-200 flex items-center justify-center gap-2 group">
                                    <span>Save New Password</span>
                                    <i data-lucide="check" class="w-5 h-5 group-hover:scale-110 transition-transform"></i>
                                </button>
                            </form>

                            <div class="mt-10 pt-8 border-t border-zinc-100 text-center">
                                <p class="text-sm text-zinc-500 font-medium">
                                    <a href="#" id="backToLogin" class="text-zinc-900 font-bold hover:underline underline-offset-4">Back to sign in</a>
                                </p>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('backToLogin').onclick = (e) => {
                e.preventDefault();
                state.authView = 'login';
                render();
            };

            document.getElementById('resetForm').onsubmit = async (e) => {
                e.preventDefault();
                const username = e.target.username.value.trim();
                const token = e.target.token.value.trim();
                const new_password = e.target.new_password.value;
                const res = await fetch('/api/auth/reset-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, token, new_password })
                });
                const data = await res.json();
                if (res.ok) {
                    state.forgotUsername = null;
                    state.authView = 'login';
                    render();
                    showToast('Password updated! You can now sign in.');
                } else {
                    renderReset(data.error || 'Something went wrong. Please try again.');
                }
            };
        }

        function renderMain() {
            const app = document.getElementById('app');
            app.innerHTML = `
                <nav class="flex items-center justify-between mb-8 md:mb-12 bg-white p-4 rounded-3xl shadow-sm border border-black/5 sticky top-4 z-40">
                    <div class="flex items-center gap-2">
                        <div class="w-10 h-10 bg-zinc-900 rounded-xl flex items-center justify-center text-white">
                            <i data-lucide="wallet"></i>
                        </div>
                        <span class="text-xl font-bold tracking-tight">IncomeTracker</span>
                    </div>
                    
                    <!-- Desktop Nav -->
                    <div class="hidden lg:flex items-center gap-1 bg-zinc-50 p-1 rounded-2xl border border-black/5">
                        <button onclick="window.setView('dashboard')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'dashboard' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Dashboard</button>
                        <button onclick="window.setView('income')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'income' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Tracking</button>
                        <button onclick="window.setView('expenses')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'expenses' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Expenses</button>
                        <button onclick="window.setView('jobs')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'jobs' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Jobs</button>
                        
                        <button onclick="window.setView('targets')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'targets' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Targets</button>
                        <button onclick="window.setView('summary')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'summary' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Summary</button>
                        ${state.user.role === 'admin' ? `<button onclick="window.setView('admin')" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'admin' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Admin</button>` : ''}
                        <button onclick="window.location.href='/notes'" class="px-6 py-2 rounded-xl text-sm font-bold transition-all ${state.currentView === 'notes' ? 'bg-white shadow-sm text-zinc-900' : 'text-zinc-400 hover:text-zinc-600'}">Notes</button>
                    </div>

                    <div class="flex items-center gap-2 md:gap-4">
                        <button type="button" onclick="window.toggleTheme()" title="Toggle light/dark theme" aria-label="Toggle light or dark theme" class="w-10 h-10 rounded-xl border border-black/5 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all">
                            <i data-lucide="${state.theme === 'dark' ? 'sun' : 'moon'}"></i>
                        </button>
                        <button type="button" onclick="window.setView('profile')" title="Account & Profile" aria-label="Account and Profile" class="flex items-center gap-2 px-3 py-1.5 rounded-xl border border-black/5 hover:bg-zinc-50 transition-all ${state.currentView === 'profile' ? 'bg-zinc-100' : ''}">
                            <i data-lucide="user" class="w-4 h-4 text-zinc-500"></i>
                            <div class="text-right hidden sm:block">
                                <p class="text-sm font-bold text-zinc-900">${escHtml(state.user.username)}</p>
                                <p class="text-[10px] text-zinc-400 uppercase font-bold tracking-widest">${escHtml(state.user.role)}</p>
                            </div>
                        </button>
                        <button type="button" onclick="window.logout()" title="Sign out" aria-label="Sign out" class="w-10 h-10 rounded-xl border border-black/5 flex items-center justify-center text-zinc-400 hover:text-red-500 hover:bg-red-50 transition-all">
                            <i data-lucide="log-out"></i>
                        </button>
                        <!-- Mobile Menu Toggle -->
                        <button type="button" onclick="window.toggleMobileMenu()" aria-label="Toggle navigation menu" class="lg:hidden w-10 h-10 rounded-xl bg-zinc-900 text-white flex items-center justify-center">
                            <i data-lucide="${state.mobileMenuOpen ? 'x' : 'menu'}"></i>
                        </button>
                    </div>
                </nav>

                <!-- Mobile Menu Overlay -->
                ${state.mobileMenuOpen ? `
                    <div class="lg:hidden fixed inset-0 z-30 bg-zinc-900/40 backdrop-blur-sm animate-fade-in" onclick="window.toggleMobileMenu()">
                        <div class="absolute top-24 left-4 right-4 bg-white rounded-[2rem] p-6 shadow-2xl border border-black/5 animate-slide" onclick="event.stopPropagation()">
                            <div class="grid grid-cols-1 gap-2">
                                <button onclick="window.setView('dashboard')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'dashboard' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="layout-dashboard"></i> Dashboard
                                </button>
                                <button onclick="window.setView('income')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'income' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="calendar"></i> Tracking
                                </button>
                                <button onclick="window.setView('expenses')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'expenses' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="receipt"></i> Expenses
                                </button>
                                <button onclick="window.setView('jobs')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'jobs' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="briefcase"></i> Jobs
                                </button>
                                
                                <button onclick="window.setView('targets')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'targets' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="target"></i> Targets
                                </button>
                                <button onclick="window.setView('summary')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'summary' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="bar-chart-3"></i> Summary
                                </button>
                                ${state.user.role === 'admin' ? `
                                    <button onclick="window.setView('admin')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'admin' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                        <i data-lucide="shield-check"></i> Admin
                                    </button>
                                ` : ''}
                                <button onclick="window.location.href='/notes'" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'notes' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="notebook-pen"></i> Notes
                                </button>
                                <button onclick="window.setView('profile')" class="flex items-center gap-4 p-4 rounded-2xl font-bold ${state.currentView === 'profile' ? 'bg-zinc-900 text-white' : 'text-zinc-500 hover:bg-zinc-50'}">
                                    <i data-lucide="user"></i> Profile
                                </button>
                            </div>
                        </div>
                    </div>
                ` : ''}

                <main id="view-content"></main>
            `;
            lucide.createIcons();
            renderView();
        }

        window.toggleMobileMenu = () => {
            state.mobileMenuOpen = !state.mobileMenuOpen;
            render();
        };

        window.setView = (view, options = { push: true }) => {
            const resolved = resolveView(view);
            if (resolved === 'notes') {
                window.location.href = '/notes';
                return;
            }
            const changed = state.currentView !== resolved;
            state.currentView = resolved;
            state.mobileMenuOpen = false;
            if (options && options.push !== false) {
                const targetUrl = viewToUrl(resolved);
                if (changed || window.location.pathname + window.location.search !== targetUrl) {
                    window.history.pushState({ view: resolved }, '', targetUrl);
                }
            }
            render();
        };

        window.changeMonth = async (delta) => {
            if (delta === 0) {
                state.selectedMonth = localYM();
            } else {
                const [year, month] = state.selectedMonth.split('-').map(Number);
                const newDate = new Date(year, month - 1 + delta, 1);
                state.selectedMonth = localYM(newDate);
            }
            await fetchStats();
            render();
        };

        window.showQuickLogModal = () => {
            const modal = document.getElementById('modal-container');
            const today = localYMD();
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-label="Quick Log Income">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide">
                        <div class="flex items-center justify-between mb-8">
                            <h3 class="text-3xl font-extrabold tracking-tight">Quick Log</h3>
                            <button type="button" onclick="this.closest('.fixed').remove()" aria-label="Close modal" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all">
                                <i data-lucide="x" class="w-5 h-5"></i>
                            </button>
                        </div>
                        <form id="quickLogForm" class="space-y-6">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Job</label>
                                <select name="job_id" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                    <option value="" disabled selected>Select a job</option>
                                    ${state.jobs.map(job => `<option value="${job.id}" data-rate="${Number(job.hourly_rate)}" data-hours="${Number(job.hours_per_day)}">${escHtml(job.name)}</option>`).join('')}
                                </select>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Date</label>
                                <input type="date" name="date" value="${today}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Amount (NTD)</label>
                                <input type="number" name="amount" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Auto-calculated from job rate">
                            </div>
                            <div class="flex gap-4 mt-10">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-emerald-500 text-white rounded-2xl font-bold hover:bg-emerald-600 transition-all shadow-lg shadow-emerald-100">Log Income</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('quickLogForm').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                if (!data.amount) {
                    const select = e.target.job_id;
                    const option = select.options[select.selectedIndex];
                    data.amount = option.dataset.rate * option.dataset.hours;
                }
                const res = await fetch('/api/income', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    closeActiveModal();
                    await fetchData();
                    render();
                    showToast('Income logged successfully!');
                } else {
                    showToast('Failed to log income', 'error');
                }
            };
        };

        window.goToReset = () => {
            state.authView = 'reset';
            render();
        };

        window.toggleTheme = () => {
            state.theme = state.theme === 'dark' ? 'light' : 'dark';
            try { localStorage.setItem('theme', state.theme); } catch (e) {}
            document.documentElement.classList.toggle('dark', state.theme === 'dark');
            render();
        };

        window.logout = async () => {
            await fetch('/api/auth/logout', { method: 'POST' });
            if (window.refreshCsrfToken) await window.refreshCsrfToken();
            destroyAllCharts();
            state.user = null;
            state.currentView = 'dashboard';
            window.history.replaceState({ view: 'dashboard' }, '', '/');
            render();
        };

        function renderView() {
            destroyAllCharts();
            const container = document.getElementById('view-content');
            if (state.currentView === 'dashboard') renderDashboard(container);
            else if (state.currentView === 'jobs') renderJobs(container);
            else if (state.currentView === 'income') renderIncome(container);
            else if (state.currentView === 'targets') renderTargets(container);
            else if (state.currentView === 'summary') renderSummary(container);
            else if (state.currentView === 'admin') renderAdmin(container);
            else if (state.currentView === 'expenses') renderExpenses(container);
            else if (state.currentView === 'profile') renderProfile(container);
        }

        function renderDashboard(container) {
            const currentMonth = state.selectedMonth;
            const monthlyIncome = state.income
                .filter(i => i.date.startsWith(currentMonth))
                .reduce((sum, i) => sum + i.amount, 0);
            const target = state.targets.find(t => t.month === currentMonth)?.amount || 0;
            const hasTarget = target > 0;
            const progress = hasTarget ? (monthlyIncome / target) * 100 : 0;
            const achieved = hasTarget && monthlyIncome >= target;
            const exceeded = hasTarget && monthlyIncome > target ? monthlyIncome - target : 0;
            
            const [year, month] = currentMonth.split('-').map(Number);
            const monthDate = new Date(year, month - 1);
            const monthName = monthDate.toLocaleString('default', { month: 'long', year: 'numeric' });
            const dayStats = getMonthDayStats(currentMonth);

            // Expenses
            const monthlyExpenses = state.expenses
                .filter(e => e.date.startsWith(currentMonth))
                .reduce((sum, e) => sum + e.amount, 0);
            const netBalance = monthlyIncome - monthlyExpenses;

            // Weekly Activity Data scoped to selectedMonth
            const weeklyWindow = getWeeklyWindowForMonth(currentMonth);
            const last7Days = weeklyWindow.days;

            const weeklyData = last7Days.map(date => {
                return state.income
                    .filter(i => i.date === date)
                    .reduce((sum, i) => sum + i.amount, 0);
            });

            const jobTotals = state.jobs.map(job => {
                return {
                    name: job.name,
                    color: job.color,
                    total: state.income
                        .filter(i => i.job_id === job.id && i.date.startsWith(currentMonth))
                        .reduce((sum, i) => sum + i.amount, 0)
                };
            }).filter(j => j.total > 0);

            container.innerHTML = `
                <div class="animate-slide space-y-6 md:space-y-8">
                    <!-- Quick Actions Bar -->
                    <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        <!-- Month Navigation -->
                        <div class="flex items-center gap-2 bg-white p-2 rounded-2xl border border-black/5 shadow-sm">
                            <button type="button" onclick="window.changeMonth(-1)" aria-label="Previous month" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-all">
                                <i data-lucide="chevron-left" class="w-5 h-5"></i>
                            </button>
                            <span class="px-4 py-2 font-bold text-zinc-900 min-w-[180px] text-center">${monthName}</span>
                            <button type="button" onclick="window.changeMonth(1)" aria-label="Next month" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 transition-all">
                                <i data-lucide="chevron-right" class="w-5 h-5"></i>
                            </button>
                            <button type="button" onclick="window.changeMonth(0)" class="px-4 py-2 rounded-xl bg-zinc-900 text-white text-xs font-bold hover:bg-zinc-800 transition-all ml-2">
                                Today
                            </button>
                        </div>
                        <!-- Quick Log Button -->
                        <button type="button" onclick="window.showQuickLogModal()" class="bg-emerald-500 text-white px-8 py-4 rounded-2xl font-bold hover:bg-emerald-600 transition-all shadow-lg shadow-emerald-100 flex items-center gap-2">
                            <i data-lucide="plus-circle" class="w-5 h-5"></i>
                            <span>Quick Log Income</span>
                        </button>
                    </div>

                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6 md:gap-8">
                        <!-- Monthly Progress Card -->
                        <div class="lg:col-span-2 bg-white p-6 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm relative overflow-hidden">
                            <div class="flex flex-col sm:flex-row justify-between items-start mb-8 md:mb-10 gap-4">
                                <div>
                                    <h2 class="text-2xl md:text-3xl font-extrabold tracking-tight mb-2">Monthly Progress</h2>
                                    <p class="text-zinc-400 font-medium text-sm">Tracking ${monthName}</p>
                                </div>
                                <div class="sm:text-right">
                                    <p class="text-3xl md:text-4xl font-black text-zinc-900">NTD ${monthlyIncome.toLocaleString()}</p>
                                    <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mt-1">Total Earnings</p>
                                </div>
                            </div>

                            <div class="space-y-4 md:space-y-6">
                                <div class="flex justify-between text-xs font-bold uppercase tracking-wider">
                                    <span class="${achieved ? 'text-emerald-500' : 'text-zinc-400'}">
                                        ${!hasTarget ? 'No Target Set' : achieved ? 'Target Achieved!' : 'Progress'}
                                    </span>
                                    <span class="text-zinc-900">${hasTarget ? progress.toFixed(1) + '%' : '—'}</span>
                                </div>
                                <div class="h-4 md:h-6 bg-zinc-50 rounded-2xl overflow-hidden p-1 border border-zinc-100">
                                    <div class="h-full rounded-xl transition-all duration-1000 ${achieved ? 'bg-emerald-500 shadow-[0_0_20px_rgba(16,185,129,0.3)]' : 'bg-zinc-900'}" style="width: ${hasTarget ? Math.min(progress, 100) : 0}%"></div>
                                </div>
                                
                                ${!hasTarget ? `
                                    <div class="flex flex-col sm:flex-row justify-between sm:items-center text-[10px] font-bold text-zinc-400 uppercase tracking-widest px-1 gap-2">
                                        <span>No monthly target set for ${monthName}</span>
                                        <button type="button" onclick="window.setView('targets')" class="text-emerald-600 hover:underline text-left sm:text-right">Set Target</button>
                                    </div>
                                ` : exceeded > 0 ? `
                                    <div class="p-4 bg-emerald-50 rounded-2xl border border-emerald-100 flex items-center justify-between animate-pulse">
                                        <div class="flex items-center gap-3 text-emerald-700">
                                            <i data-lucide="sparkles" class="w-4 h-4 md:w-5 md:h-5"></i>
                                            <span class="font-bold text-sm">Exceeded Target by</span>
                                        </div>
                                        <span class="text-emerald-700 font-black text-base md:text-lg">NTD ${exceeded.toLocaleString()}</span>
                                    </div>
                                ` : `
                                    <div class="flex flex-col sm:flex-row justify-between sm:items-center text-[10px] font-bold text-zinc-400 uppercase tracking-widest px-1 gap-2">
                                        <span>Target: NTD ${target.toLocaleString()}</span>
                                        <span>Remaining: NTD ${Math.max(0, target - monthlyIncome).toLocaleString()}</span>
                                    </div>
                                `}
                            </div>
                        </div>

                        <!-- Daily Average Card -->
                        <div class="bg-zinc-900 p-6 md:p-10 rounded-[2.5rem] text-white flex flex-col justify-between relative overflow-hidden group">
                            <div class="absolute -right-10 -top-10 w-40 h-40 bg-white/5 rounded-full blur-3xl group-hover:bg-white/10 transition-all duration-700"></div>
                            <div>
                                <div class="w-12 h-12 md:w-14 md:h-14 bg-white/10 backdrop-blur-md rounded-2xl flex items-center justify-center mb-6 md:mb-8">
                                    <i data-lucide="trending-up" class="text-emerald-400"></i>
                                </div>
                                <h3 class="text-zinc-400 text-[10px] font-bold uppercase tracking-[0.2em] mb-2">Daily Average</h3>
                                <p class="text-4xl md:text-5xl font-black tracking-tighter">NTD ${(monthlyIncome / dayStats.divisor).toFixed(0)}</p>
                            </div>
                            <div class="mt-6 md:mt-8 pt-6 md:pt-8 border-t border-white/10">
                                <p class="text-[10px] md:text-xs font-medium text-zinc-500 leading-relaxed">Based on your activity over ${dayStats.label}.</p>
                            </div>
                        </div>
                    </div>

                    <!-- Charts Row -->
                    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 md:gap-8">
                        <div class="bg-white p-6 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <div class="flex justify-between items-center mb-8 md:mb-10">
                                <div>
                                    <h3 class="text-lg md:text-xl font-extrabold tracking-tight">Weekly Activity</h3>
                                    <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mt-1">${weeklyWindow.subtitle}</p>
                                </div>
                                <div class="flex items-center gap-2">
                                    <span class="w-2 h-2 md:w-3 md:h-3 bg-zinc-900 rounded-full"></span>
                                    <span class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">Earnings</span>
                                </div>
                            </div>
                            <div class="h-[250px] md:h-[300px]">
                                <canvas id="weeklyChart"></canvas>
                            </div>
                        </div>

                        <div class="bg-white p-6 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <div class="flex justify-between items-center mb-8 md:mb-10">
                                <h3 class="text-lg md:text-xl font-extrabold tracking-tight">Income by Job</h3>
                                <div class="flex items-center gap-4">
                                    <button type="button" onclick="window.setView('summary')" class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 hover:text-zinc-900 transition-colors">View All</button>
                                </div>
                            </div>
                            <div class="h-[250px] md:h-[300px]">
                                ${jobTotals.length === 0
                                    ? `<div class="h-full flex flex-col items-center justify-center text-center text-zinc-400 gap-2">
                                        <i data-lucide="pie-chart" class="w-8 h-8 opacity-40"></i>
                                        <p class="text-sm font-medium">No income recorded for ${monthName}</p>
                                    </div>`
                                    : `<canvas id="jobChart"></canvas>`}
                            </div>
                        </div>
                    </div>
                    <!-- Expenses -->
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-6">
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Income</p>
                            <p class="text-2xl font-black text-emerald-600">NTD ${monthlyIncome.toLocaleString()}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Expenses</p>
                            <p class="text-2xl font-black text-red-500">NTD ${monthlyExpenses.toLocaleString()}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Net Balance</p>
                            <p class="text-2xl font-black ${netBalance >= 0 ? 'text-zinc-900' : 'text-red-600'}">NTD ${netBalance.toLocaleString()}</p>
                        </div>
                    </div>
                </div>
                <div id="modal-container"></div>
            `;
            lucide.createIcons();

            // Weekly Activity Chart (Line)
            createChart('weeklyChart', {
                type: 'line',
                data: {
                    labels: last7Days.map(d => d.slice(5)),
                    datasets: [{
                        label: 'Earnings',
                        data: weeklyData,
                        borderColor: isDarkTheme() ? '#e4e4e7' : '#18181b',
                        backgroundColor: isDarkTheme() ? 'rgba(228, 228, 231, 0.08)' : 'rgba(24, 24, 27, 0.05)',
                        fill: true,
                        tension: 0.4,
                        borderWidth: 4,
                        pointRadius: 6,
                        pointBackgroundColor: isDarkTheme() ? '#17171b' : '#fff',
                        pointBorderColor: isDarkTheme() ? '#e4e4e7' : '#18181b',
                        pointBorderWidth: 3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, grid: { display: false }, ticks: { font: { weight: 'bold' }, color: chartColors() } },
                        x: { grid: { display: false }, ticks: { font: { weight: 'bold' }, color: chartColors() } }
                    }
                }
            });

            if (jobTotals.length > 0) {
                createChart('jobChart', {
                    type: 'doughnut',
                    data: {
                        labels: jobTotals.map(j => j.name),
                        datasets: [{
                            data: jobTotals.map(j => j.total),
                            backgroundColor: jobTotals.map(j => j.color),
                            borderWidth: 0,
                            hoverOffset: 20
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        cutout: '75%',
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: {
                                    padding: 20,
                                    usePointStyle: true,
                                    color: chartColors(),
                                    font: { weight: 'bold', size: 11 }
                                }
                            }
                        }
                    }
                });
            }
        }

        // Add more view renders as needed...
        function renderJobs(container) {
            container.innerHTML = `
                <div class="animate-slide space-y-8">
                    <div class="flex justify-between items-center">
                        <div>
                            <h2 class="text-3xl font-extrabold tracking-tight">Job Profiles</h2>
                            <p class="text-zinc-500 font-medium">Manage your different income sources.</p>
                        </div>
                        <button onclick="window.showJobModal()" class="bg-zinc-900 text-white px-8 py-4 rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-200 flex items-center gap-2">
                            <i data-lucide="plus" class="w-5 h-5"></i>
                            <span>Add New Job</span>
                        </button>
                    </div>
                    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                        ${state.jobs.length === 0 ? `
                            <div class="col-span-full bg-white p-12 rounded-[2.5rem] border border-black/5 shadow-sm text-center">
                                <div class="w-14 h-14 mx-auto mb-4 rounded-2xl bg-zinc-50 flex items-center justify-center text-zinc-400">
                                    <i data-lucide="briefcase" class="w-6 h-6"></i>
                                </div>
                                <h3 class="text-lg font-extrabold text-zinc-900 mb-1">No job profiles yet</h3>
                                <p class="text-sm text-zinc-400 mb-6">Add your first job to start tracking income automatically.</p>
                                <button type="button" onclick="window.showJobModal()" class="bg-zinc-900 text-white px-6 py-3 rounded-2xl text-sm font-bold hover:bg-zinc-800 transition-all">Add New Job</button>
                            </div>
                        ` : state.jobs.map(job => {
                            const totalEarned = state.income
                                .filter(i => i.job_id === job.id)
                                .reduce((sum, i) => sum + i.amount, 0);
                            const totalEarnedMonth = state.income
                                .filter(i => i.job_id === job.id && i.date.startsWith(state.selectedMonth))
                                .reduce((sum, i) => sum + i.amount, 0);
                            return `
                                <div class="bg-white p-8 rounded-[2.5rem] border border-black/5 shadow-sm group relative overflow-hidden transition-all hover:shadow-xl hover:-translate-y-1">
                                    <div class="absolute top-0 left-0 w-full h-2" style="background-color: ${escHtml(job.color)}"></div>
                                    <div class="flex justify-between items-start mb-6">
                                        <div class="w-12 h-12 rounded-2xl flex items-center justify-center text-white shadow-lg" style="background-color: ${escHtml(job.color)}">
                                            <i data-lucide="briefcase" class="w-6 h-6"></i>
                                        </div>
                                        <div class="flex gap-2">
                                            <button type="button" onclick="window.showJobModal(${escHandlerArg(job.id)})" aria-label="Edit job ${escAttr(job.name)}" class="w-8 h-8 rounded-lg bg-zinc-50 text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 flex items-center justify-center transition-all">
                                                <i data-lucide="edit-3" class="w-4 h-4"></i>
                                            </button>
                                            <button type="button" onclick="window.deleteJob(${Number(job.id)})" aria-label="Delete job ${escAttr(job.name)}" class="w-8 h-8 rounded-lg bg-zinc-50 text-zinc-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-all">
                                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                                            </button>
                                        </div>
                                    </div>
                                    <h4 class="text-2xl font-extrabold mb-6 tracking-tight">${escHtml(job.name)}</h4>
                                    <div class="space-y-4">
                                        <div class="flex justify-between items-center p-3 bg-zinc-50 rounded-xl">
                                            <span class="text-xs font-bold uppercase tracking-widest text-zinc-400">Hourly Rate</span>
                                            <span class="font-black text-zinc-900">NTD ${Number(job.hourly_rate).toLocaleString()}</span>
                                        </div>
                                        <div class="flex justify-between items-center p-3 bg-zinc-50 rounded-xl">
                                            <span class="text-xs font-bold uppercase tracking-widest text-zinc-400">Daily Hours</span>
                                            <span class="font-black text-zinc-900">${Number(job.hours_per_day)}h</span>
                                        </div>
                                    </div>
                                    <div class="mt-6 pt-6 border-t border-zinc-100 flex justify-between items-center">
                                        <span class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400">Est. Daily</span>
                                        <span class="text-lg font-black text-zinc-900">NTD ${(Number(job.hourly_rate) * Number(job.hours_per_day)).toLocaleString()}</span>
                                    </div>
                                    <div class="mt-4 pt-4 border-t border-zinc-100 flex justify-between items-center">
                                        <span class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400">Total Money</span>
                                        <span class="text-lg font-black text-emerald-600">NTD ${totalEarned.toLocaleString()}</span>
                                    </div>
                                    <div class="mt-2 flex justify-between items-center">
                                        <span class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400">This Month</span>
                                        <span class="text-sm font-black text-zinc-700">NTD ${totalEarnedMonth.toLocaleString()}</span>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
                <div id="modal-container"></div>
            `;
            lucide.createIcons();
        }

        window.showJobModal = (jobId = null) => {
            const job = jobId == null ? null : state.jobs.find(j => j.id === Number(jobId));
            const modal = document.getElementById('modal-container');
            const colors = ['#18181b', '#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4'];
            const defaultColor = job ? job.color : colors[state.jobs.length % colors.length];
            
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide relative overflow-hidden">
                        <div class="absolute top-0 left-0 w-full h-2" id="modal-accent" style="background-color: ${escHtml(defaultColor)}"></div>
                        <h3 class="text-3xl font-extrabold mb-8 tracking-tight">${job ? 'Edit Job Profile' : 'New Job Profile'}</h3>
                        <form id="jobForm" class="space-y-6">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Job Name</label>
                                <input type="text" name="name" value="${escHtml(job ? job.name : '')}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="e.g. Freelance Design" required>
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Rate (NTD/hr)</label>
                                    <input type="number" name="hourly_rate" value="${job ? Number(job.hourly_rate) : ''}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Hours/Day</label>
                                    <input type="number" name="hours_per_day" value="${job ? Number(job.hours_per_day) : ''}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-3 ml-1">Profile Color</label>
                                <div class="flex flex-wrap gap-3">
                                    ${colors.map(c => `
                                        <label class="cursor-pointer">
                                            <input type="radio" name="color" value="${c}" class="hidden peer" ${ defaultColor === c ? 'checked' : ''} onchange="document.getElementById('modal-accent').style.backgroundColor = this.value">
                                            <div class="w-8 h-8 rounded-full border-4 border-white shadow-sm ring-1 ring-zinc-200 peer-checked:ring-zinc-900 transition-all" style="background-color: ${c}"></div>
                                        </label>
                                    `).join('')}
                                </div>
                            </div>
                            <div class="flex gap-4 mt-10">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-100">${job ? 'Update Job' : 'Create Job'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;
            document.getElementById('jobForm').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                const url = job ? `/api/jobs/${job.id}` : '/api/jobs';
                const method = job ? 'PUT' : 'POST';
                
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    await fetchData();
                    render();
                } else {
                    const err = await res.json();
                    alert('Error saving job: ' + (err.error || 'Unknown error'));
                }
            };
        };

        window.deleteJob = async (id) => {
            if (!confirm('Delete this job profile?')) return;
            const res = await fetch(`/api/jobs/${id}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                alert(err.error || 'Could not delete this job.');
                return;
            }
            await fetchData();
            render();
        };

        function renderIncome(container) {
            const currentMonth = state.selectedMonth;
            const [year, month] = currentMonth.split('-').map(Number);
            const daysInMonth = new Date(year, month, 0).getDate();
            const firstDay = new Date(year, month - 1, 1).getDay();
            const monthName = new Date(year, month - 1).toLocaleString('default', { month: 'long', year: 'numeric' });
            
            const incomeByDay = {};
            state.income.filter(i => i.date.startsWith(currentMonth)).forEach(i => {
                const day = parseInt(i.date.split('-')[2]);
                if (!incomeByDay[day]) incomeByDay[day] = [];
                incomeByDay[day].push(i);
            });

            container.innerHTML = `
                <div class="animate-slide space-y-8">
                    <div class="flex justify-between items-center">
                        <div>
                            <h2 class="text-3xl font-extrabold tracking-tight">Daily Tracking</h2>
                            <p class="text-zinc-500 font-medium">Visualize your daily activity and log earnings.</p>
                        </div>
                        <button onclick="window.showAddIncomeModal()" class="bg-zinc-900 text-white px-8 py-4 rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-200 flex items-center gap-2">
                            <i data-lucide="plus" class="w-5 h-5"></i>
                            <span>Log Income</span>
                        </button>
                    </div>

                    <div id="work-pace-panel" class="mb-0"></div>

                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        <!-- Calendar View -->
                        <div class="lg:col-span-2 bg-white p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <div class="flex justify-between items-center mb-8">
                                <h3 class="text-xl font-extrabold tracking-tight">${monthName}</h3>
                                <div class="flex gap-2">
                                    <button onclick="window.changeMonth(-1)" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all"><i data-lucide="chevron-left" class="w-5 h-5"></i></button>
                                    <button onclick="window.changeMonth(1)" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all"><i data-lucide="chevron-right" class="w-5 h-5"></i></button>
                                </div>
                            </div>
                            <div class="grid grid-cols-7 gap-4">
                                ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map(d => `<div class="text-center text-[10px] font-bold uppercase tracking-widest text-zinc-400 pb-4">${d}</div>`).join('')}
                                ${Array(firstDay).fill(0).map(() => `<div class="aspect-square"></div>`).join('')}
                                ${Array(daysInMonth).fill(0).map((_, i) => {
                                    const day = i + 1;
                                    const dateStr = `${year}-${month.toString().padStart(2, '0')}-${day.toString().padStart(2, '0')}`;
                                    const records = incomeByDay[day] || [];
                                    const mainJob = records.length > 0 ? state.jobs.find(j => j.id === records[0].job_id) : null;
                                    const total = records.reduce((sum, r) => sum + r.amount, 0);
                                    
                                    return `
                                        <div onclick="window.showAddIncomeModal(${escHandlerArg(dateStr)})" class="aspect-square rounded-2xl border border-zinc-100 p-2 flex flex-col justify-between transition-all hover:border-zinc-900 cursor-pointer relative group" 
                                             style="${mainJob ? `background-color: ${escHtml(mainJob.color)}15; border-color: ${escHtml(mainJob.color)}40;` : ''}">
                                            <span class="text-xs font-bold ${mainJob ? 'text-zinc-900' : 'text-zinc-400'}">${day}</span>
                                            ${total > 0 ? `<span class="text-[10px] font-black text-zinc-900 truncate">NTD ${total.toLocaleString()}</span>` : ''}
                                            ${records.length > 0 ? `
                                                <div class="absolute inset-0 bg-zinc-900/90 rounded-2xl opacity-0 group-hover:opacity-100 transition-all flex items-center justify-center p-2 z-10">
                                                    <p class="text-[8px] text-white font-bold leading-tight">${escHtml(records.map(r => r.job_name).join(', '))}</p>
                                                </div>
                                            ` : ''}
                                        </div>
                                    `;
                                }).join('')}
                            </div>
                        </div>

                        <!-- Records List -->
                        <div class="bg-white rounded-[2.5rem] border border-black/5 shadow-sm overflow-hidden flex flex-col">
                            <div class="p-8 border-b border-zinc-100 flex justify-between items-center bg-zinc-50/50">
                                <h3 class="font-bold text-zinc-900 flex items-center gap-2">
                                    <i data-lucide="list" class="w-5 h-5 text-zinc-400"></i>
                                    Records
                                </h3>
                                <button onclick="window.toggleTable()" class="text-xs font-bold uppercase tracking-widest text-zinc-400 hover:text-zinc-900 transition-colors">
                                    <i data-lucide="maximize-2" class="w-4 h-4"></i>
                                </button>
                            </div>
                            <div id="incomeTableContainer" class="flex-1 overflow-y-auto max-h-[600px] transition-all duration-500">
                                <div class="divide-y divide-zinc-100">
                                    ${state.income.length === 0 ? `
                                        <div class="p-10 text-center text-zinc-400">
                                            <p class="text-sm font-medium">No income records yet.</p>
                                            <p class="text-xs mt-1">Click a day on the calendar to log your first entry.</p>
                                        </div>
                                    ` : state.income.slice().sort((a,b) => b.date.localeCompare(a.date)).map(record => {
                                        const job = state.jobs.find(j => j.id === record.job_id);
                                        return `
                                            <div class="p-6 hover:bg-zinc-50/50 transition-all group flex items-center justify-between">
                                                <div class="flex items-center gap-4">
                                                    <div class="w-12 h-12 rounded-2xl flex items-center justify-center text-white shadow-sm" style="background-color: ${escHtml(job ? job.color : '#e2e8f0')}">
                                                        <i data-lucide="calendar" class="w-5 h-5"></i>
                                                    </div>
                                                    <div>
                                                        <p class="font-black text-zinc-900">NTD ${Number(record.amount).toLocaleString()}</p>
                                                        <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">${escHtml(record.date)} • ${escHtml(record.job_name)}</p>
                                                    </div>
                                                </div>
                                                <div class="flex gap-2 opacity-100 md:opacity-0 md:group-hover:opacity-100 transition-all">
                                                    <button type="button" onclick="window.editIncome(${Number(record.id)}, ${Number(record.amount)}, ${Number(record.job_id)}, ${escHandlerArg(record.date)})" aria-label="Edit income record" class="w-10 h-10 rounded-xl bg-zinc-50 text-zinc-400 hover:text-zinc-900 hover:bg-zinc-100 flex items-center justify-center transition-all">
                                                        <i data-lucide="edit-3" class="w-4 h-4"></i>
                                                    </button>
                                                    <button type="button" onclick="window.deleteIncome(${Number(record.id)})" aria-label="Delete income record" class="w-10 h-10 rounded-xl bg-zinc-50 text-zinc-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-all">
                                                        <i data-lucide="trash-2" class="w-4 h-4"></i>
                                                    </button>
                                                </div>
                                            </div>
                                        `;
                                    }).join('')}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div id="modal-container"></div>
            `;
            lucide.createIcons();
            renderWorkPacePanel();
        }

        function renderWorkPacePanel() {
            var panel = document.getElementById('work-pace-panel');
            if (!panel) return;

            var T = document.documentElement.classList.contains('dark');
            var C = T ? {
                cardBg: '#1f1f24', cardBorder: 'rgba(255,255,255,.06)', line: '#2b2b31',
                title: '#fafafa', soft: '#7c7c85', accentTile: '#fafafa',
                accentTileIcon: '#18181b', pillOn: '#fafafa', pillOnText: '#18181b',
                pillOffBg: '#26262b', pillOffText: '#7c7c85', pillOffBorder: '#2f2f35',
                bar: '#fafafa', track: '#2f2f35', dotOn: '#fafafa', dotOnBorder: '#fafafa',
                dotOff: '#33333a', dotOffBorder: '#3f3f46', danger: '#f87171'
            } : {
                cardBg: '#fff', cardBorder: 'rgba(0,0,0,.05)', line: '#f4f4f5',
                title: '#18181b', soft: '#a1a1aa', accentTile: '#18181b',
                accentTileIcon: '#fff', pillOn: '#18181b', pillOnText: '#fff',
                pillOffBg: '#f9fafb', pillOffText: '#a1a1aa', pillOffBorder: '#f4f4f5',
                bar: '#18181b', track: '#f4f4f5', dotOn: '#18181b', dotOnBorder: '#18181b',
                dotOff: '#f4f4f5', dotOffBorder: '#e4e4e7', danger: '#ef4444'
            };

            var now = new Date();
            var currentMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
            var dayOfMonth = now.getDate();
            var totalDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();

            // Find current month target
            var target = null;
            for (var i = 0; i < state.targets.length; i++) {
                if (state.targets[i].month === currentMonth) { target = state.targets[i]; break; }
            }
            var targetAmt = target ? parseFloat(target.amount) : 0;
            var wdpw = (target && target.work_days_per_week != null) ? parseFloat(target.work_days_per_week) : null;

            // Sum income this month
            var earned = 0;
            for (var i = 0; i < state.income.length; i++) {
                if (state.income[i].date.slice(0, 7) === currentMonth) earned += parseFloat(state.income[i].amount);
            }

            if (!targetAmt) { panel.innerHTML = ''; return; }

            // Build 1-7 day selector pills
            var pills = '';
            for (var d = 1; d <= 7; d++) {
                var sel = (wdpw === d);
                pills += '<button type="button" onclick="window.saveWorkDays(' + d + ')" style="'
                    + (sel ? 'background:' + C.pillOn + ';color:' + C.pillOnText + ';border-color:' + C.pillOn + ';' : 'background:' + C.pillOffBg + ';color:' + C.pillOffText + ';border-color:' + C.pillOffBorder + ';')
                    + '" class="py-2 px-3 rounded-xl border text-xs font-bold transition-all hover:border-zinc-400 cursor-pointer">' + d + 'd</button>';
            }

            // Stats when days are set
            var statsHTML = '';
            if (wdpw !== null) {
                var totalWorkDays = Math.round((wdpw / 7) * totalDays);
                var doneWorkDays  = Math.max(0, Math.round((wdpw / 7) * (dayOfMonth - 1)));
                var leftWorkDays  = Math.max(0, totalWorkDays - doneWorkDays);

                // Estimated completion
                var compLabel = '—';
                var compNote  = 'Log income to get an estimate';
                var compStyle = 'color:' + C.title;
                var noteStyle = 'color:' + C.soft;

                if (earned >= targetAmt) {
                    compLabel = 'Done!';
                    compNote  = 'Target already reached this month';
                    compStyle = 'color:#10b981';
                    noteStyle = 'color:#10b981';
                } else if (doneWorkDays > 0) {
                    var dailyRate = earned / doneWorkDays;
                    if (dailyRate > 0) {
                        var daysNeeded   = Math.ceil((targetAmt - earned) / dailyRate);
                        var calNeeded    = Math.ceil(daysNeeded / (wdpw / 7));
                        var estDate      = new Date(now);
                        estDate.setDate(now.getDate() + calNeeded);
                        var endOfMonth   = new Date(now.getFullYear(), now.getMonth() + 1, 0);
                        var months       = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                        compLabel = months[estDate.getMonth()] + ' ' + estDate.getDate();
                        if (estDate > endOfMonth) {
                            compNote  = 'Behind pace \u2014 may miss this month';
                            compStyle = 'color:#ef4444';
                            noteStyle = 'color:' + C.danger;
                        } else {
                            compNote  = 'Estimated completion this month';
                        }
                    }
                }

                // Progress bar
                var pct = Math.min(100, (earned / targetAmt) * 100).toFixed(1);
                var barColor = earned >= targetAmt ? '#10b981' : C.bar;

                // Dot trail
                var dots = '';
                for (var k = 0; k < totalWorkDays; k++) {
                    dots += '<div style="width:8px;height:8px;border-radius:50%;background:' + (k < doneWorkDays ? C.dotOn : C.dotOff) + ';border:1px solid ' + (k < doneWorkDays ? C.dotOnBorder : C.dotOffBorder) + '"></div>';
                }

                statsHTML = '<div style="display:grid;grid-template-columns:1fr 1fr;border-top:1px solid ' + C.line + '">'
                    // Left: days left
                    + '<div style="padding:28px 32px;border-right:1px solid ' + C.line + '">'
                    + '<p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.15em;color:' + C.soft + ';margin-bottom:6px">Working days left</p>'
                    + '<p style="font-size:48px;font-weight:900;color:' + C.title + ';line-height:1">' + leftWorkDays + '</p>'
                    + '<p style="font-size:11px;color:' + C.soft + ';margin-top:6px">' + doneWorkDays + ' done &middot; ' + totalWorkDays + ' total this month</p>'
                    + '<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:12px">' + dots + '</div>'
                    + '</div>'
                    // Right: estimated completion
                    + '<div style="padding:28px 32px">'
                    + '<p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.15em;color:' + C.soft + ';margin-bottom:6px">Est. completion</p>'
                    + '<p style="font-size:48px;font-weight:900;line-height:1;' + compStyle + '">' + compLabel + '</p>'
                    + '<p style="font-size:11px;margin-top:6px;' + noteStyle + '">' + compNote + '</p>'
                    + '<div style="margin-top:16px">'
                    + '<div style="display:flex;justify-content:space-between;font-size:10px;font-weight:700;color:' + C.soft + ';margin-bottom:4px">'
                    + '<span>NTD ' + Math.round(earned).toLocaleString() + '</span><span>/ NTD ' + targetAmt.toLocaleString() + '</span>'
                    + '</div>'
                    + '<div style="height:6px;background:' + C.track + ';border-radius:999px;overflow:hidden">'
                    + '<div style="height:100%;border-radius:999px;background:' + barColor + ';width:' + pct + '%;transition:width .6s"></div>'
                    + '</div></div>'
                    + '</div>'
                    + '</div>';
            } else {
                statsHTML = '<div style="padding:20px 32px;color:' + C.soft + ';font-size:13px;border-top:1px solid ' + C.line + '">'
                    + 'Select days per week above to see working days left and estimated completion date.'
                    + '</div>';
            }

            panel.innerHTML = '<div style="background:' + C.cardBg + ';border-radius:2.5rem;border:1px solid ' + C.cardBorder + ';box-shadow:0 1px 3px rgba(0,0,0,.08);overflow:hidden;margin-bottom:32px">'
                + '<div style="padding:24px 32px;border-bottom:1px solid ' + C.line + ';display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:16px">'
                + '<div style="display:flex;align-items:center;gap:12px">'
                + '<div style="width:40px;height:40px;background:' + C.accentTile + ';border-radius:12px;display:flex;align-items:center;justify-content:center;flex-shrink:0">'
                + '<i data-lucide="calendar-clock" style="width:18px;height:18px;color:' + C.accentTileIcon + '"></i>'
                + '</div>'
                + '<div>'
                + '<p style="font-size:15px;font-weight:800;color:' + C.title + '">Work Schedule</p>'
                + '<p style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.15em;color:' + C.soft + '">'
                + (wdpw ? wdpw + ' days / week' : 'How many days per week will you work?')
                + '</p>'
                + '</div></div>'
                + '<div style="display:flex;gap:6px;flex-wrap:wrap">' + pills + '</div>'
                + '</div>'
                + statsHTML
                + '</div>';

            lucide.createIcons();
        }

        window.saveWorkDays = async function(days) {
            var now = new Date();
            var currentMonth = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
            var target = null;
            for (var i = 0; i < state.targets.length; i++) {
                if (state.targets[i].month === currentMonth) { target = state.targets[i]; break; }
            }
            if (!target) { alert('Please set a monthly target first on the Targets page.'); return; }
            var res = await fetch('/api/targets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ month: currentMonth, amount: target.amount, work_days_per_week: days })
            });
            if (res.ok) {
                var updated = await res.json();
                for (var i = 0; i < state.targets.length; i++) {
                    if (state.targets[i].month === currentMonth) { state.targets[i] = updated; break; }
                }
                renderWorkPacePanel();
            }
        };

        window.toggleTable = () => {
            const container = document.getElementById('incomeTableContainer');
            if (container.style.maxHeight === '0px') {
                container.style.maxHeight = '2000px';
                container.style.opacity = '1';
            } else {
                container.style.maxHeight = '0px';
                container.style.opacity = '0';
            }
        };

        window.showAddIncomeModal = (prefilledDate = null) => {
            const modal = document.getElementById('modal-container');
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide">
                        <h3 class="text-3xl font-extrabold mb-8 tracking-tight">Log Income</h3>
                        <form id="addIncomeForm" class="space-y-6">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Select Job</label>
                                <select name="job_id" id="jobSelect" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium appearance-none" required onchange="window.updateSelectColor(this)">
                                    <option value="" disabled selected>Choose a job profile</option>
                                    ${state.jobs.map(job => `<option value="${job.id}" data-color="${escHtml(job.color)}" data-rate="${Number(job.hourly_rate)}" data-hours="${Number(job.hours_per_day)}">${escHtml(job.name)}</option>`).join('')}
                                </select>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Date</label>
                                <input type="date" name="date" id="dateInput" value="${escHtml(prefilledDate || localYMD())}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required onchange="window.updateDateColor(this)">
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Amount (NTD)</label>
                                <div class="relative">
                                    <input type="number" name="amount" id="amountInput" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="Leave empty to use job default">
                                    <div id="amountHint" class="absolute right-4 top-1/2 -translate-y-1/2 text-[10px] font-bold text-zinc-400 uppercase tracking-widest hidden">
                                        Default: NTD 0
                                    </div>
                                </div>
                            </div>
                            <div class="flex gap-4 mt-10">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-100">Log Entry</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;

            document.getElementById('addIncomeForm').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                
                const res = await fetch('/api/income', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                if (res.ok) {
                    await fetchData();
                    document.querySelector('.fixed').remove();
                    render();
                    showToast('Income logged successfully!');
                } else {
                    const err = await res.json();
                    showToast(err.error || 'Failed to log income', 'error');
                }
            };
        };

        window.updateSelectColor = (select) => {
            const option = select.options[select.selectedIndex];
            const color = option.dataset.color;
            const rate = option.dataset.rate;
            const hours = option.dataset.hours;
            
            select.style.borderColor = color;
            select.style.color = color;

            const hint = document.getElementById('amountHint');
            if (rate && hours) {
                hint.innerText = `Default: NTD ${(rate * hours).toLocaleString()}`;
                hint.classList.remove('hidden');
            } else {
                hint.classList.add('hidden');
            }
        };

        window.updateDateColor = (input) => {
            // Just a visual feedback
            input.style.borderColor = '#10b981';
        };

        window.deleteIncome = async (id) => {
            if (confirm('Delete this income record?')) {
                const res = await fetch(`/api/income/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    await fetchData();
                    render();
                    showToast('Income record deleted');
                } else {
                    showToast('Failed to delete record', 'error');
                }
            }
        };

        window.editIncome = async (id, currentAmount, currentJobId, currentDate) => {
            const modal = document.getElementById('modal-container');
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide">
                        <h3 class="text-3xl font-extrabold mb-8 tracking-tight">Edit Income</h3>
                        <form id="editIncomeForm" class="space-y-6">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Job</label>
                                <select name="job_id" id="editJobSelect" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                    ${state.jobs.map(job => `<option value="${job.id}" ${job.id == currentJobId ? 'selected' : ''} data-rate="${Number(job.hourly_rate)}" data-hours="${Number(job.hours_per_day)}">${escHtml(job.name)}</option>`).join('')}
                                </select>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Date</label>
                                <input type="date" name="date" value="${escHtml(currentDate)}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Amount (NTD)</label>
                                <input type="number" name="amount" value="${Number(currentAmount)}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                            </div>
                            <div class="flex gap-4 mt-10">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-100">Update</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;

            document.getElementById('editIncomeForm').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                const res = await fetch(`/api/income/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                if (res.ok) {
                    await fetchData();
                    document.querySelector('.fixed').remove();
                    render();
                    showToast('Income updated successfully!');
                } else {
                    const err = await res.json();
                    showToast(err.error || 'Failed to update income', 'error');
                }
            };
        };

        function renderTargets(container) {
            const currentMonth = state.selectedMonth;
            const [year, month] = currentMonth.split('-').map(Number);
            const monthName = new Date(year, month - 1).toLocaleString('default', { month: 'long', year: 'numeric' });
            const monthlyIncome = state.income
                .filter(i => i.date.startsWith(currentMonth))
                .reduce((sum, i) => sum + i.amount, 0);
            const target = state.targets.find(t => t.month === currentMonth)?.amount || 0;
            const hasTarget = target > 0;
            const progress = hasTarget ? (monthlyIncome / target) * 100 : 0;
            const achieved = hasTarget && monthlyIncome >= target;
            const exceeded = hasTarget && monthlyIncome > target ? monthlyIncome - target : 0;
            const sortedTargets = [...state.targets].sort((a, b) => b.month.localeCompare(a.month));

            container.innerHTML = `
                <div class="animate-slide space-y-8">
                    <div class="flex justify-between items-center">
                        <div>
                            <h2 class="text-3xl font-extrabold tracking-tight">Income Targets</h2>
                            <p class="text-zinc-500 font-medium">Set goals and visualize your financial growth.</p>
                        </div>
                        <button type="button" onclick="window.showSetTargetModal()" class="bg-zinc-900 text-white px-8 py-4 rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-200 flex items-center gap-2">
                            <i data-lucide="target" class="w-5 h-5"></i>
                            <span>Set Monthly Target</span>
                        </button>
                    </div>

                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        <div class="lg:col-span-2 bg-white p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <div class="flex justify-between items-center mb-10">
                                <h3 class="text-xl font-extrabold tracking-tight">Month Progress</h3>
                                <div class="flex items-center gap-2">
                                    <button type="button" onclick="window.changeMonth(-1)" aria-label="Previous month" class="w-8 h-8 rounded-lg bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all">
                                        <i data-lucide="chevron-left" class="w-4 h-4"></i>
                                    </button>
                                    <span class="px-4 py-2 bg-zinc-50 rounded-xl text-xs font-bold text-zinc-400 uppercase tracking-widest">${monthName}</span>
                                    <button type="button" onclick="window.changeMonth(1)" aria-label="Next month" class="w-8 h-8 rounded-lg bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all">
                                        <i data-lucide="chevron-right" class="w-4 h-4"></i>
                                    </button>
                                </div>
                            </div>
                            
                            <div class="relative h-64 flex items-center justify-center mb-10">
                                <canvas id="progressCircle"></canvas>
                                <div class="absolute inset-0 flex flex-col items-center justify-center">
                                    <span class="text-5xl font-black text-zinc-900">${hasTarget ? progress.toFixed(0) + '%' : '—'}</span>
                                    <span class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mt-1">${hasTarget ? 'Achieved' : 'No Target'}</span>
                                </div>
                            </div>

                            <div class="grid grid-cols-2 gap-6">
                                <div class="p-6 bg-zinc-50 rounded-3xl border border-zinc-100">
                                    <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2">Current Income</p>
                                    <p class="text-2xl font-black text-zinc-900">NTD ${monthlyIncome.toLocaleString()}</p>
                                </div>
                                <div class="p-6 bg-zinc-50 rounded-3xl border border-zinc-100">
                                    <p class="text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2">Target Goal</p>
                                    <p class="text-2xl font-black text-zinc-900">${hasTarget ? 'NTD ' + target.toLocaleString() : 'Not set'}</p>
                                </div>
                            </div>
                        </div>

                        <div class="space-y-8">
                            <div class="bg-zinc-900 p-10 rounded-[2.5rem] text-white relative overflow-hidden">
                                <h3 class="text-xl font-extrabold mb-6 tracking-tight">Analytics</h3>
                                <div class="space-y-6">
                                    <div>
                                        <div class="flex justify-between text-xs font-bold uppercase tracking-widest text-zinc-500 mb-2">
                                            <span>Status</span>
                                            <span class="${achieved ? 'text-emerald-400' : 'text-zinc-400'}">${!hasTarget ? 'No Target' : achieved ? 'Completed' : 'In Progress'}</span>
                                        </div>
                                        <div class="h-2 bg-white/5 rounded-full overflow-hidden">
                                            <div class="h-full bg-emerald-400" style="width: ${hasTarget ? Math.min(progress, 100) : 0}%"></div>
                                        </div>
                                    </div>
                                    ${!hasTarget ? `
                                        <div class="pt-6 border-t border-white/10">
                                            <p class="text-xs font-bold uppercase tracking-widest text-zinc-500 mb-2">No Target Set</p>
                                            <p class="text-sm font-medium text-zinc-400">Set a target for ${monthName} to track goal progress.</p>
                                        </div>
                                    ` : exceeded > 0 ? `
                                        <div class="pt-6 border-t border-white/10">
                                            <p class="text-xs font-bold uppercase tracking-widest text-zinc-500 mb-2">Exceeding by</p>
                                            <p class="text-3xl font-black text-emerald-400">NTD ${exceeded.toLocaleString()}</p>
                                            <p class="text-[10px] font-medium text-zinc-500 mt-2">You've surpassed your goal! Keep it up.</p>
                                        </div>
                                    ` : `
                                        <div class="pt-6 border-t border-white/10">
                                            <p class="text-xs font-bold uppercase tracking-widest text-zinc-500 mb-2">Remaining</p>
                                            <p class="text-3xl font-black text-white">NTD ${Math.max(0, target - monthlyIncome).toLocaleString()}</p>
                                        </div>
                                    `}
                                </div>
                            </div>
                            
                            <div class="bg-white p-8 rounded-[2.5rem] border border-black/5 shadow-sm">
                                <h3 class="text-lg font-extrabold mb-4 tracking-tight">Target History</h3>
                                <div class="space-y-4 max-h-[200px] overflow-y-auto pr-2">
                                    ${sortedTargets.length === 0 ? `
                                        <p class="text-sm text-zinc-400 text-center py-6">No targets set yet.</p>
                                    ` : sortedTargets.map(t => `
                                        <div class="flex justify-between items-center p-4 bg-zinc-50 rounded-2xl border border-zinc-100 gap-3">
                                            <div>
                                                <p class="text-xs font-bold text-zinc-900">${escHtml(t.month)}</p>
                                                <p class="text-[10px] text-zinc-400 font-medium">Monthly Target</p>
                                            </div>
                                            <div class="flex items-center gap-3">
                                                <span class="font-black text-zinc-900">NTD ${Number(t.amount).toLocaleString()}</span>
                                                <button type="button" onclick="window.deleteTarget(${Number(t.id)})" aria-label="Delete target for ${escAttr(t.month)}" class="w-8 h-8 rounded-lg bg-white text-zinc-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-all border border-zinc-100">
                                                    <i data-lucide="trash-2" class="w-3.5 h-3.5"></i>
                                                </button>
                                            </div>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <div id="modal-container"></div>
            `;
            lucide.createIcons();

            // Progress Circle Chart
            createChart('progressCircle', {
                type: 'doughnut',
                data: {
                    datasets: [{
                        data: hasTarget ? [monthlyIncome, Math.max(0, target - monthlyIncome)] : [0, 1],
                        backgroundColor: [achieved ? '#10b981' : '#18181b', isDarkTheme() ? '#26262b' : '#f4f4f5'],
                        borderWidth: 0,
                        circumference: 360,
                        rotation: 0
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '85%',
                    plugins: { legend: { display: false }, tooltip: { enabled: false } }
                }
            });
        }

        window.deleteTarget = async (id) => {
            if (!confirm('Delete this monthly target?')) return;
            const res = await fetch(`/api/targets/${id}`, { method: 'DELETE' });
            if (res.ok) {
                await fetchData();
                render();
                showToast('Target deleted');
            } else {
                const err = await res.json().catch(() => ({}));
                showToast(err.error || 'Failed to delete target', 'error');
            }
        };

        window.showSetTargetModal = () => {
            const modal = document.getElementById('modal-container');
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-label="Set Target">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide">
                        <h3 class="text-3xl font-extrabold mb-8 tracking-tight">Set Target</h3>
                        <form id="setTargetForm" class="space-y-6">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Month</label>
                                <input type="month" name="month" value="${escAttr(state.selectedMonth)}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Target Amount (NTD)</label>
                                <input type="number" name="amount" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="0" required>
                            </div>
                            <div class="flex gap-4 mt-10">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-100">Save Target</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;
            document.getElementById('setTargetForm').onsubmit = async (e) => {
                e.preventDefault();
                const formData = new FormData(e.target);
                const data = Object.fromEntries(formData.entries());
                await fetch('/api/targets', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                await fetchData();
                render();
            };
        };

        function renderSummary(container) {
            const currentMonth = state.selectedMonth;
            const [summaryYear, summaryMonth] = currentMonth.split('-').map(Number);
            const summaryMonthName = new Date(summaryYear, summaryMonth - 1).toLocaleString('default', { month: 'long', year: 'numeric' });
            const summaryTotal = state.income
                .filter(i => i.date.startsWith(currentMonth))
                .reduce((sum, i) => sum + i.amount, 0);

            container.innerHTML = `
                <div class="animate-slide space-y-6 md:space-y-8">
                    <div class="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                        <div>
                            <h2 class="text-2xl md:text-3xl font-extrabold tracking-tight">Monthly Summary</h2>
                            <p class="text-zinc-500 font-medium text-sm mt-1">${summaryMonthName} • Total Income: NTD ${summaryTotal.toLocaleString()}</p>
                        </div>
                        <div class="flex items-center gap-2 bg-zinc-100 p-1 rounded-2xl border border-black/5 self-start sm:self-auto">
                            <button type="button" onclick="window.changeMonth(-1)" aria-label="Previous month" class="w-8 h-8 md:w-10 md:h-10 rounded-xl flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all"><i data-lucide="chevron-left" class="w-4 h-4"></i></button>
                            <button type="button" onclick="window.changeMonth(0)" class="px-4 py-2 ${currentMonth === localYM() ? 'bg-white shadow-sm' : 'bg-zinc-50'} rounded-xl text-[10px] md:text-xs font-bold text-zinc-900">${currentMonth === localYM() ? 'Current Month' : summaryMonthName + ' (back to today)'}</button>
                            <button type="button" onclick="window.changeMonth(1)" aria-label="Next month" class="w-8 h-8 md:w-10 md:h-10 rounded-xl flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all"><i data-lucide="chevron-right" class="w-4 h-4"></i></button>
                        </div>
                    </div>

                    <!-- Chart Section -->
                    <div class="bg-white p-6 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm relative overflow-hidden">
                        <div class="flex justify-between items-center mb-8 md:mb-10">
                            <div>
                                <h3 class="text-lg md:text-xl font-extrabold tracking-tight">Income Analysis</h3>
                                <p class="text-zinc-400 text-[10px] md:text-xs font-medium mt-1">Select chart type below</p>
                            </div>
                            <div class="flex gap-2 bg-zinc-50 p-1 rounded-xl border border-black/5">
                                <button type="button" onclick="window.setSummaryChart('bar')" class="px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all bg-zinc-900 text-white" id="chartBtn-bar">Bar</button>
                                <button type="button" onclick="window.setSummaryChart('line')" class="px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider text-zinc-400 hover:text-zinc-900 transition-all" id="chartBtn-line">Line</button>
                                <button type="button" onclick="window.setSummaryChart('polarArea')" class="px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider text-zinc-400 hover:text-zinc-900 transition-all" id="chartBtn-polarArea">Polar</button>
                            </div>
                        </div>
                        <div class="h-[300px] md:h-[400px] relative">
                            ${summaryTotal === 0
                                ? `<div class="h-full flex flex-col items-center justify-center text-center text-zinc-400 gap-2">
                                    <i data-lucide="bar-chart-3" class="w-8 h-8 opacity-40"></i>
                                    <p class="text-sm font-medium">No income recorded for ${summaryMonthName}</p>
                                </div>`
                                : `<canvas id="summaryChart"></canvas>`}
                        </div>
                    </div>

                    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
                        ${state.jobs.length === 0 ? `
                            <div class="col-span-full bg-white p-10 rounded-3xl border border-black/5 shadow-sm text-center text-zinc-400">
                                <p class="text-sm font-medium">No job profiles yet. Create a job to see per-job breakdowns.</p>
                            </div>
                        ` : state.jobs.map(job => {
                            const total = state.income
                                .filter(i => i.job_id === job.id && i.date.startsWith(currentMonth))
                                .reduce((sum, i) => sum + i.amount, 0);
                            return `
                                <div class="bg-white p-6 rounded-3xl border border-black/5 shadow-sm">
                                    <div class="flex items-center gap-3 mb-4">
                                        <div class="w-2 h-6 rounded-full" style="background-color: ${escHtml(job.color)}"></div>
                                        <h4 class="font-bold text-zinc-900 truncate text-sm md:text-base">${escHtml(job.name)}</h4>
                                    </div>
                                    <p class="text-xl md:text-2xl font-black text-zinc-900">NTD ${total.toLocaleString()}</p>
                                    <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mt-1">This Month</p>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
            lucide.createIcons();

            let currentChartType = 'bar';

            window.setSummaryChart = (type) => {
                currentChartType = type;
                document.querySelectorAll('[id^="chartBtn-"]').forEach(btn => {
                    btn.className = btn.className.replace('bg-zinc-900 text-white', 'text-zinc-400 hover:text-zinc-900');
                    btn.className = btn.className.replace('bg-emerald-500 text-white', 'text-zinc-400 hover:text-zinc-900');
                });
                const activeBtn = document.getElementById('chartBtn-' + type);
                if (activeBtn) {
                    activeBtn.className = activeBtn.className.replace('text-zinc-400 hover:text-zinc-900', 'bg-emerald-500 text-white');
                }
                updateSummaryChart();
            };

            const updateSummaryChart = () => {
                if (summaryTotal === 0) return;
                const jobTotals = state.jobs.map(job => {
                    return {
                        name: job.name,
                        color: job.color,
                        total: state.income
                            .filter(i => i.job_id === job.id && i.date.startsWith(currentMonth))
                            .reduce((sum, i) => sum + i.amount, 0)
                    };
                }).filter(j => j.total > 0);
                if (jobTotals.length === 0) return;

                createChart('summaryChart', {
                    type: currentChartType,
                    data: {
                        labels: jobTotals.map(j => j.name),
                        datasets: [{
                            label: 'Income NTD',
                            data: jobTotals.map(j => j.total),
                            backgroundColor: currentChartType === 'line' ? (isDarkTheme() ? 'rgba(228, 228, 231, 0.08)' : 'rgba(24, 24, 27, 0.05)') : jobTotals.map(j => j.color),
                            borderColor: currentChartType === 'line' ? (isDarkTheme() ? '#e4e4e7' : '#18181b') : 'transparent',
                            borderWidth: currentChartType === 'line' ? 4 : 0,
                            fill: currentChartType === 'line',
                            tension: 0.4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                display: currentChartType === 'polarArea',
                                labels: { color: chartColors() }
                            }
                        },
                        scales: currentChartType === 'polarArea' ? {} : {
                            y: { beginAtZero: true, grid: { display: false }, ticks: { color: chartColors() } },
                            x: { grid: { display: false }, ticks: { color: chartColors() } }
                        }
                    }
                });
            };

            updateSummaryChart();
        }

        async function renderAdmin(container) {
            container.innerHTML = '<div class="flex items-center justify-center py-20"><div class="animate-spin rounded-full h-10 w-10 border-b-2 border-zinc-900"></div></div>';
            let usersRes, statsRes;
            try {
                [usersRes, statsRes] = await Promise.all([
                    fetch('/api/admin/users'),
                    fetch('/api/admin/stats')
                ]);
            } catch (e) {
                if (state.currentView !== 'admin') return;
                container.innerHTML = '<div class="bg-white p-10 rounded-[2.5rem] border border-black/5 text-center text-red-500 font-bold">Network error loading admin data.</div>';
                return;
            }
            if (state.currentView !== 'admin') return;
            if (!usersRes.ok || !statsRes.ok) {
                container.innerHTML = '<div class="bg-white p-10 rounded-[2.5rem] border border-black/5 text-center text-red-500 font-bold">Unable to load admin data.</div>';
                return;
            }
            const users = await usersRes.json();
            const stats = await statsRes.json();
            if (state.currentView !== 'admin') return;
            const dailyTrend = Array.isArray(stats.daily_trend) ? stats.daily_trend : [];
            const hasTrendData = dailyTrend.some(d => Number(d.total) > 0);
            
            container.innerHTML = `
                <div class="animate-slide space-y-8">
                    <div class="flex justify-between items-center">
                        <div>
                            <h2 class="text-3xl font-extrabold tracking-tight">Admin Control</h2>
                            <p class="text-zinc-500 font-medium">System overview and user management.</p>
                        </div>
                    </div>

                    <!-- Stats Grid -->
                    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Users</p>
                            <p class="text-3xl font-black text-zinc-900">${stats.total_users}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Jobs</p>
                            <p class="text-3xl font-black text-zinc-900">${stats.total_jobs}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Records</p>
                            <p class="text-3xl font-black text-zinc-900">${stats.total_records}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">System Income</p>
                            <p class="text-2xl font-black text-emerald-600">NTD ${Number(stats.total_income || 0).toLocaleString()}</p>
                        </div>
                    </div>

                    <!-- 30-Day Income Trend -->
                    <div class="bg-white p-6 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                        <div class="flex justify-between items-center mb-6">
                            <div>
                                <h3 class="text-lg md:text-xl font-extrabold tracking-tight">30-Day Income Trend</h3>
                                <p class="text-xs text-zinc-400 font-medium mt-1">System-wide daily income across all users</p>
                            </div>
                        </div>
                        <div class="h-[240px]">
                            ${hasTrendData
                                ? `<canvas id="adminTrendChart"></canvas>`
                                : `<div class="h-full flex flex-col items-center justify-center text-zinc-400 gap-2">
                                    <i data-lucide="trending-up" class="w-8 h-8 opacity-40"></i>
                                    <p class="text-sm font-medium">No income recorded in the past 30 days</p>
                                </div>`}
                        </div>
                    </div>

                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
                        <!-- User Management -->
                        <div class="lg:col-span-2 bg-white rounded-[2.5rem] border border-black/5 shadow-sm overflow-hidden">
                            <div class="p-8 border-b border-zinc-100 bg-zinc-50/50">
                                <h3 class="font-bold text-zinc-900 flex items-center gap-2">
                                    <i data-lucide="users" class="w-5 h-5 text-zinc-400"></i>
                                    User Directory
                                </h3>
                            </div>
                            <div class="overflow-x-auto">
                                <table class="w-full text-left">
                                    <thead class="bg-zinc-50/30 border-b border-zinc-100">
                                        <tr>
                                            <th class="px-8 py-4 text-[10px] font-bold uppercase tracking-wider text-zinc-400">User</th>
                                            <th class="px-8 py-4 text-[10px] font-bold uppercase tracking-wider text-zinc-400">Role</th>
                                            <th class="px-8 py-4 text-[10px] font-bold uppercase tracking-wider text-zinc-400 text-right">Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-zinc-100">
                                        ${users.map(user => `
                                            <tr class="hover:bg-zinc-50/50 transition-all group">
                                                <td class="px-8 py-5">
                                                    <div class="flex items-center gap-3">
                                                        <div class="w-10 h-10 rounded-full bg-zinc-100 flex items-center justify-center font-bold text-zinc-400">
                                                            ${escHtml(user.username[0].toUpperCase())}
                                                        </div>
                                                        <span class="font-bold text-zinc-900">${escHtml(user.username)}</span>
                                                    </div>
                                                </td>
                                                <td class="px-8 py-5">
                                                    <select onchange="window.updateUserRole(${user.id}, this.value)" aria-label="Role for ${escAttr(user.username)}" class="bg-zinc-100 border-none rounded-lg text-[10px] font-bold uppercase tracking-widest px-3 py-1 outline-none focus:ring-2 focus:ring-zinc-900 transition-all">
                                                        <option value="user" ${user.role === 'user' ? 'selected' : ''}>User</option>
                                                        <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>Admin</option>
                                                    </select>
                                                </td>
                                                <td class="px-8 py-5 text-right">
                                                    <div class="flex items-center justify-end gap-2">
                                                        <button type="button" onclick="window.generateResetCode(${escHandlerArg(user.username)})" title="Generate password reset code" aria-label="Generate reset code for ${escAttr(user.username)}" class="w-10 h-10 rounded-xl bg-zinc-50 text-zinc-400 hover:text-emerald-600 hover:bg-emerald-50 flex items-center justify-center transition-all">
                                                            <i data-lucide="key-round" class="w-4 h-4"></i>
                                                        </button>
                                                        <button type="button" onclick="window.deleteUser(${user.id})" title="Delete user" aria-label="Delete user ${escAttr(user.username)}" class="w-10 h-10 rounded-xl bg-zinc-50 text-zinc-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-all">
                                                            <i data-lucide="user-minus" class="w-4 h-4"></i>
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        `).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>

                        <!-- Recent Activity -->
                        <div class="bg-white rounded-[2.5rem] border border-black/5 shadow-sm overflow-hidden">
                            <div class="p-8 border-b border-zinc-100 bg-zinc-50/50">
                                <h3 class="font-bold text-zinc-900 flex items-center gap-2">
                                    <i data-lucide="activity" class="w-5 h-5 text-zinc-400"></i>
                                    Recent Activity
                                </h3>
                            </div>
                            <div class="divide-y divide-zinc-100">
                                ${stats.recent_activity.length === 0 ? `
                                    <div class="p-10 text-center text-sm text-zinc-400">No recent income activity.</div>
                                ` : stats.recent_activity.map(act => `
                                    <div class="p-6 hover:bg-zinc-50/30 transition-all">
                                        <div class="flex justify-between items-start mb-1">
                                            <p class="text-sm font-bold text-zinc-900">${escHtml(act.username)}</p>
                                            <span class="text-[10px] font-black text-emerald-600">NTD ${Number(act.amount).toLocaleString()}</span>
                                        </div>
                                        <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">${escHtml(act.date)} • ${escHtml(act.job_name)}</p>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>
                </div>
                <div id="modal-container"></div>
            `;
            lucide.createIcons();

            if (hasTrendData) {
                createChart('adminTrendChart', {
                    type: 'line',
                    data: {
                        labels: dailyTrend.map(d => d.date.slice(5)),
                        datasets: [{
                            label: 'Daily Income (NTD)',
                            data: dailyTrend.map(d => d.total),
                            borderColor: '#10b981',
                            backgroundColor: 'rgba(16, 185, 129, 0.12)',
                            fill: true,
                            tension: 0.35,
                            borderWidth: 3,
                            pointRadius: 3
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            y: { beginAtZero: true, grid: { display: false }, ticks: { color: chartColors() } },
                            x: { grid: { display: false }, ticks: { color: chartColors(), maxTicksLimit: 10 } }
                        }
                    }
                });
            }
        }

        window.generateResetCode = async (username) => {
            try {
                const res = await fetch('/api/auth/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    showToast(data.error || `Failed to generate reset code (HTTP ${res.status})`, 'error');
                    return;
                }
                const token = data.reset_token;
                if (!token) {
                    showToast('Reset code could not be retrieved', 'error');
                    return;
                }
                const modal = document.getElementById('modal-container');
                if (!modal) return;
                modal.innerHTML = `
                    <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4" role="dialog" aria-modal="true" aria-label="Password Reset Code">
                        <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide">
                            <div class="flex items-center justify-between mb-6">
                                <h3 class="text-2xl font-extrabold tracking-tight">Password Reset Code</h3>
                                <button type="button" onclick="this.closest('.fixed').remove()" aria-label="Close modal" class="w-10 h-10 rounded-xl bg-zinc-50 flex items-center justify-center text-zinc-400 hover:text-zinc-900 transition-all">
                                    <i data-lucide="x" class="w-5 h-5"></i>
                                </button>
                            </div>
                            <p class="text-sm text-zinc-500 mb-4">Share this single-use reset code with <strong class="text-zinc-900">${escHtml(username)}</strong>. It expires in 30 minutes.</p>
                            <div class="p-4 rounded-2xl bg-zinc-50 border border-zinc-100 font-mono text-sm break-all select-all text-zinc-900 mb-6" id="admin-reset-token-box">${escHtml(token)}</div>
                            <div class="flex gap-3">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-3.5 border border-zinc-100 rounded-2xl font-bold text-zinc-500 hover:bg-zinc-50 transition-all">Close</button>
                                <button type="button" id="copy-reset-token-btn" class="flex-1 py-3.5 bg-emerald-500 text-white rounded-2xl font-bold hover:bg-emerald-600 transition-all flex items-center justify-center gap-2">
                                    <i data-lucide="copy" class="w-4 h-4"></i>
                                    <span>Copy Code</span>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
                lucide.createIcons();
                const copyBtn = document.getElementById('copy-reset-token-btn');
                if (copyBtn) {
                    copyBtn.onclick = async () => {
                        try {
                            await navigator.clipboard.writeText(token);
                            showToast('Reset code copied to clipboard');
                        } catch (e) {
                            showToast('Select and copy the code manually', 'error');
                        }
                    };
                }
            } catch (e) {
                showToast('Network error generating reset code', 'error');
            }
        };

        window.updateUserRole = async (id, role) => {
            const res = await fetch(`/api/admin/users/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role })
            });
            if (res.ok) {
                render();
            } else {
                const err = await res.json();
                alert(err.error || 'Failed to update role');
                render();
            }
        };

        window.deleteUser = async (id) => {
            if (confirm('Delete this user? This action cannot be undone.')) {
                await fetch(`/api/admin/users/${id}`, { method: 'DELETE' });
                render();
            }
        };


        function renderExpenses(container) {
            const currentMonth = state.selectedMonth;
            const monthlyExpenses = state.expenses.filter(e => e.date.startsWith(currentMonth));
            const totalMonthly = monthlyExpenses.reduce((sum, e) => sum + e.amount, 0);
            const monthlyIncome = state.income
                .filter(i => i.date.startsWith(currentMonth))
                .reduce((sum, i) => sum + i.amount, 0);
            const netBalance = monthlyIncome - totalMonthly;

            // Type config
            const typeConfig = {
                'daily':    { label: 'Daily',      color: '#3b82f6', icon: 'coffee'       },
                'bills':    { label: 'Bills',       color: '#8b5cf6', icon: 'file-text'    },
                'work':     { label: 'Work',        color: '#f59e0b', icon: 'briefcase'    },
                'one-time': { label: 'One-time',    color: '#ec4899', icon: 'shopping-bag' }
            };

            // Aggregate by type for chart
            const byType = {};
            monthlyExpenses.forEach(e => {
                byType[e.expense_type] = (byType[e.expense_type] || 0) + e.amount;
            });

            // All unique tags across all expenses
            const allTags = [...new Set(
                state.expenses.flatMap(e => e.tags.filter(t => t))
            )];

            // Tag totals this month
            const byTag = {};
            monthlyExpenses.forEach(e => {
                e.tags.forEach(t => {
                    if (t) byTag[t] = (byTag[t] || 0) + e.amount;
                });
            });

            // Weekly spend scoped to selectedMonth
            const dayStats = getMonthDayStats(currentMonth);
            const weeklyWindow = getWeeklyWindowForMonth(currentMonth);
            const last7 = weeklyWindow.days;
            const weeklySpend = last7.map(date =>
                state.expenses.filter(e => e.date === date).reduce((s, e) => s + e.amount, 0)
            );

            const stats = state.expenseStats;
            const monthStats = stats && stats.month === currentMonth ? stats : null;
            const budgetCards = Object.entries(typeConfig).map(([type, cfg]) => {
                const b = monthStats ? monthStats.budgets[type] : null;
                const spent = b ? b.spent : (byType[type] || 0);
                if (!b || b.status === 'unset') {
                    return { type, cfg, spent, limit: null, percent: null, bar: 0, status: 'unset' };
                }
                const bar = b.status === 'over' ? 100 : (b.percent ?? 0);
                return { type, cfg, spent, limit: b.limit_amount, percent: b.percent, bar, status: b.status };
            });
            const overBudgetCount = budgetCards.filter(b => b.status === 'over').length;

            container.innerHTML = `
                <div class="animate-slide space-y-8">

                    <!-- Header -->
                    <div class="flex flex-col sm:flex-row justify-between sm:items-center gap-4">
                        <div>
                            <h2 class="text-3xl font-extrabold tracking-tight">Expenses</h2>
                            <p class="text-zinc-500 font-medium">Track and tag your daily costs.</p>
                        </div>
                        <button onclick="window.showExpenseModal()" class="bg-zinc-900 text-white px-8 py-4 rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg shadow-zinc-200 flex items-center gap-2 self-start sm:self-auto">
                            <i data-lucide="plus" class="w-5 h-5"></i>
                            <span>Add Expense</span>
                        </button>
                    </div>

                    <!-- KPI Row -->
                    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">This Month</p>
                            <p class="text-2xl font-black text-red-500">NTD ${totalMonthly.toLocaleString()}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Net Balance</p>
                            <p class="text-2xl font-black ${netBalance >= 0 ? 'text-emerald-600' : 'text-red-600'}">NTD ${netBalance.toLocaleString()}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Daily Average</p>
                            <p class="text-2xl font-black text-zinc-900">NTD ${(totalMonthly / dayStats.divisor).toFixed(0)}</p>
                        </div>
                        <div class="bg-white p-6 rounded-[2rem] border border-black/5 shadow-sm">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400 mb-2">Total Records</p>
                            <p class="text-2xl font-black text-zinc-900">${monthlyExpenses.length}</p>
                        </div>
                    </div>

                    <!-- Monthly Budgets -->
                    <div class="bg-white p-8 md:p-10 rounded-[2.5rem] border ${overBudgetCount > 0 ? 'border-red-200' : 'border-black/5'} shadow-sm">
                        <div class="flex flex-col sm:flex-row justify-between sm:items-center gap-4 mb-8">
                            <div>
                                <h3 class="text-xl font-extrabold tracking-tight flex items-center gap-2">
                                    Monthly Budgets
                                    ${overBudgetCount > 0 ? `<span class="px-2 py-0.5 bg-red-50 border border-red-200 rounded-full text-[10px] font-bold text-red-500 uppercase tracking-wider">${overBudgetCount} over</span>` : ''}
                                </h3>
                                <p class="text-xs text-zinc-400 font-medium mt-1">Spending limits for ${escHtml(currentMonth)}</p>
                            </div>
                            <button onclick="window.showBudgetModal()" class="px-5 py-2.5 border border-zinc-100 rounded-2xl text-xs font-bold text-zinc-500 hover:bg-zinc-50 transition-all flex items-center gap-2 self-start sm:self-auto">
                                <i data-lucide="sliders-horizontal" class="w-4 h-4"></i>
                                Edit Budgets
                            </button>
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                            ${budgetCards.map(b => {
                                const barColor = b.status === 'over' ? '#ef4444' : b.status === 'warning' ? '#f59e0b' : b.cfg.color;
                                const statusLabel = b.status === 'over' ? 'Over budget' : b.status === 'warning' ? 'Almost there' : b.status === 'ok' ? 'On track' : 'No limit set';
                                const statusCls = b.status === 'over' ? 'text-red-500' : b.status === 'warning' ? 'text-amber-500' : 'text-zinc-400';
                                return `
                                <div class="p-5 rounded-3xl border ${b.status === 'over' ? 'border-red-200 bg-red-50/40' : b.status === 'warning' ? 'border-amber-200 bg-amber-50' : 'border-zinc-100 bg-zinc-50/50'}">
                                    <div class="flex justify-between items-center mb-3">
                                        <span class="text-xs font-bold uppercase tracking-wider flex items-center gap-2" style="color:${escHtml(b.cfg.color)}">
                                            <i data-lucide="${escHtml(b.cfg.icon)}" class="w-4 h-4"></i>${escHtml(b.cfg.label)}
                                        </span>
                                        <span class="text-[10px] font-bold uppercase tracking-wider ${statusCls}">${statusLabel}</span>
                                    </div>
                                    ${b.limit === null ? `
                                        <p class="text-sm text-zinc-400 font-medium">Spent NTD ${b.spent.toLocaleString()}</p>
                                    ` : `
                                        <div class="flex justify-between items-baseline mb-2">
                                            <span class="text-lg font-black text-zinc-900">NTD ${b.spent.toLocaleString()}</span>
                                            <span class="text-xs font-bold text-zinc-400">/ ${b.limit.toLocaleString()}</span>
                                        </div>
                                        <div class="h-2 bg-zinc-100 rounded-full overflow-hidden">
                                            <div class="h-full rounded-full transition-all" style="width:${Math.min(b.bar, 100).toFixed(1)}%;background:${barColor}"></div>
                                        </div>
                                        <p class="text-[10px] font-bold mt-2 ${statusCls}">${b.percent === null ? '—' : b.percent.toFixed(0) + '%'} used${b.status === 'over' ? ` · NTD ${(b.spent - b.limit).toLocaleString()} over` : ''}</p>
                                    `}
                                </div>`;
                            }).join('')}
                        </div>
                    </div>

                    <!-- Charts Row -->
                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">

                        <!-- Weekly Spend Chart -->
                        <div class="lg:col-span-2 bg-white p-8 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <div class="flex justify-between items-center mb-8">
                                <div>
                                    <h3 class="text-xl font-extrabold tracking-tight">Weekly Spending</h3>
                                    <p class="text-xs text-zinc-400 font-medium mt-1">${weeklyWindow.subtitle}</p>
                                </div>
                                <span class="w-3 h-3 rounded-full bg-red-400"></span>
                            </div>
                            <div class="h-[260px]">
                                <canvas id="expenseWeeklyChart"></canvas>
                            </div>
                        </div>

                        <!-- By Type Doughnut -->
                        <div class="bg-white p-8 md:p-10 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <h3 class="text-xl font-extrabold tracking-tight mb-8">By Category</h3>
                            <div class="h-[180px]">
                                ${Object.keys(byType).length === 0
                                    ? `<div class="h-full flex flex-col items-center justify-center text-zinc-400 gap-2">
                                        <i data-lucide="pie-chart" class="w-7 h-7 opacity-40"></i>
                                        <p class="text-xs font-medium">No expenses this month</p>
                                    </div>`
                                    : `<canvas id="expenseTypeChart"></canvas>`}
                            </div>
                            <div class="mt-6 space-y-3">
                                ${Object.entries(byType).map(([type, amt]) => `
                                    <div class="flex justify-between items-center">
                                        <div class="flex items-center gap-2">
                                            <span class="w-2 h-2 rounded-full" style="background:${escHtml(typeConfig[type]?.color || '#ccc')}"></span>
                                            <span class="text-xs font-bold text-zinc-500 uppercase tracking-wider">${escHtml(typeConfig[type]?.label || type)}</span>
                                        </div>
                                        <span class="text-sm font-black text-zinc-900">NTD ${amt.toLocaleString()}</span>
                                    </div>
                                `).join('')}
                            </div>
                        </div>
                    </div>

                    <!-- Tags Section + List -->
                    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">

                        <!-- Tag Breakdown -->
                        <div class="bg-white p-8 rounded-[2.5rem] border border-black/5 shadow-sm">
                            <h3 class="text-lg font-extrabold tracking-tight mb-6">Tags This Month</h3>
                            ${Object.keys(byTag).length === 0
                                ? `<p class="text-sm text-zinc-400">No tagged expenses yet.</p>`
                                : `<div class="space-y-4">
                                    ${Object.entries(byTag).sort((a,b) => b[1]-a[1]).map(([tag, amt]) => {
                                        const pct = totalMonthly > 0 ? (amt / totalMonthly * 100) : 0;
                                        return `
                                        <div>
                                            <div class="flex justify-between items-center mb-1">
                                                <span class="text-xs font-bold text-zinc-700 flex items-center gap-1">
                                                    <span class="px-2 py-0.5 bg-zinc-100 rounded-full text-[10px] font-bold text-zinc-500">#${escHtml(tag)}</span>
                                                </span>
                                                <span class="text-xs font-black text-zinc-900">NTD ${amt.toLocaleString()}</span>
                                            </div>
                                            <div class="h-2 bg-zinc-50 rounded-full overflow-hidden">
                                                <div class="h-full bg-zinc-800 rounded-full" style="width:${pct.toFixed(1)}%"></div>
                                            </div>
                                        </div>`;
                                    }).join('')}
                                </div>`
                            }
                        </div>

                        <!-- Expense List -->
                        <div class="lg:col-span-2 bg-white rounded-[2.5rem] border border-black/5 shadow-sm overflow-hidden">
                            <div class="p-6 border-b border-zinc-100 flex justify-between items-center bg-zinc-50/50">
                                <h3 class="font-bold text-zinc-900 flex items-center gap-2">
                                    <i data-lucide="receipt" class="w-5 h-5 text-zinc-400"></i>
                                    All Expenses
                                </h3>
                                <div class="flex gap-2 flex-wrap" id="expense-tag-filters">
                                    <button onclick="window.filterExpenseTag(null)" class="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-zinc-900 text-white transition-all" data-tag="all">All</button>
                                    ${allTags.slice(0, 6).map(tag => `
                                        <button onclick="window.filterExpenseTag(${escHandlerArg(tag)})" class="px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-zinc-100 text-zinc-500 hover:bg-zinc-200 transition-all" data-tag="${escHtml(tag)}">#${escHtml(tag)}</button>
                                    `).join('')}
                                </div>
                            </div>
                            <div id="expense-list-body" class="divide-y divide-zinc-50 max-h-[520px] overflow-y-auto">
                                ${renderExpenseRows(state.expenses)}
                            </div>
                        </div>

                    </div>
                </div>
                <div id="expense-modal-container"></div>
            `;

            lucide.createIcons();

            // Weekly chart
            const barColors = [
                { bg: 'rgba(59,130,246,0.15)',  border: '#3b82f6' },
                { bg: 'rgba(139,92,246,0.15)',  border: '#8b5cf6' },
                { bg: 'rgba(245,158,11,0.15)',  border: '#f59e0b' },
                { bg: 'rgba(236,72,153,0.15)',  border: '#ec4899' },
                { bg: 'rgba(16,185,129,0.15)',  border: '#10b981' },
                { bg: 'rgba(239,68,68,0.15)',   border: '#ef4444' },
                { bg: 'rgba(99,102,241,0.15)',  border: '#6366f1' },
            ];
            createChart('expenseWeeklyChart', {
                type: 'bar',
                data: {
                    labels: last7.map(d => d.slice(5)),
                    datasets: [{
                        label: 'Spent',
                        data: weeklySpend,
                        backgroundColor: last7.map((_, i) => barColors[i % barColors.length].bg),
                        borderColor: last7.map((_, i) => barColors[i % barColors.length].border),
                        borderWidth: 2,
                        borderRadius: 8,
                        hoverBackgroundColor: last7.map((_, i) => barColors[i % barColors.length].border.replace(')', ', 0.35)').replace('rgb', 'rgba')),
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        y: { beginAtZero: true, grid: { display: false }, ticks: { font: { weight: 'bold' }, color: chartColors() } },
                        x: { grid: { display: false }, ticks: { font: { weight: 'bold' }, color: chartColors() } }
                    }
                }
            });

            // By-type doughnut
            const typeEntries = Object.entries(byType);
            if (typeEntries.length > 0) {
                createChart('expenseTypeChart', {
                    type: 'doughnut',
                    data: {
                        labels: typeEntries.map(([t]) => typeConfig[t]?.label || t),
                        datasets: [{
                            data: typeEntries.map(([,v]) => v),
                            backgroundColor: typeEntries.map(([t]) => typeConfig[t]?.color || '#ccc'),
                            borderWidth: 0, hoverOffset: 12
                        }]
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false, cutout: '72%',
                        plugins: { legend: { display: false } }
                    }
                });
            }
        }

        function renderExpenseRows(expenses, tagFilter = null) {
            const typeConfig = {
                'daily':    { label: 'Daily',    color: '#3b82f6' },
                'bills':    { label: 'Bills',    color: '#8b5cf6' },
                'work':     { label: 'Work',     color: '#f59e0b' },
                'one-time': { label: 'One-time', color: '#ec4899' }
            };
            let filtered = tagFilter
                ? expenses.filter(e => e.tags.includes(tagFilter))
                : expenses;

            if (!filtered.length) return `<div class="p-10 text-center text-sm text-zinc-400">No expenses found.</div>`;

            return [...filtered].sort((a,b) => b.date.localeCompare(a.date)).map(e => {
                const cfg = typeConfig[e.expense_type] || { label: e.expense_type, color: '#aaa' };
                const cfgLabel = escHtml(cfg.label);
                const cfgColor = escHtml(cfg.color);
                return `
                    <div class="p-5 hover:bg-zinc-50/50 transition-all group flex items-center justify-between gap-4">
                        <div class="flex items-center gap-4 min-w-0">
                            <div class="w-11 h-11 rounded-2xl flex items-center justify-center text-white shrink-0" style="background-color:${cfg.color}20">
                                <span class="text-[10px] font-black" style="color:${cfgColor}">${escHtml(cfgLabel.slice(0,3).toUpperCase())}</span>
                            </div>
                            <div class="min-w-0">
                                <p class="font-bold text-zinc-900 truncate">${escHtml(e.description)}</p>
                                <div class="flex items-center gap-2 mt-1 flex-wrap">
                                    <span class="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">${e.date}</span>
                                    ${e.tags.filter(t=>t).map(t =>
                                        `<span class="px-2 py-0.5 bg-zinc-100 rounded-full text-[10px] font-bold text-zinc-500">#${escHtml(t)}</span>`
                                    ).join('')}
                                </div>
                            </div>
                        </div>
                        <div class="flex items-center gap-3 shrink-0">
                            <span class="font-black text-zinc-900 mono">NTD ${e.amount.toLocaleString()}</span>
                            <button onclick="window.deleteExpense(${e.id})" class="w-8 h-8 rounded-xl bg-zinc-50 text-zinc-300 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-all opacity-0 group-hover:opacity-100">
                                <i data-lucide="trash-2" class="w-4 h-4"></i>
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        }

        window.filterExpenseTag = (tag) => {
            const body = document.getElementById('expense-list-body');
            if (!body) return;
            body.innerHTML = renderExpenseRows(state.expenses, tag);
            lucide.createIcons();
            // Update active button style
            document.querySelectorAll('#expense-tag-filters button').forEach(btn => {
                const isActive = (tag === null && btn.dataset.tag === 'all') || btn.dataset.tag === tag;
                btn.className = isActive
                    ? 'px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-zinc-900 text-white transition-all'
                    : 'px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-zinc-100 text-zinc-500 hover:bg-zinc-200 transition-all';
            });
        };

        window.showExpenseModal = (expense = null) => {
            const modal = document.getElementById('expense-modal-container');
            const existingTags = expense ? expense.tags.join(', ') : '';
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide relative overflow-hidden">
                        <div class="absolute top-0 left-0 w-full h-2 bg-red-400"></div>
                        <h3 class="text-3xl font-extrabold mb-8 tracking-tight">${expense ? 'Edit Expense' : 'Add Expense'}</h3>
                        <form id="expenseForm" class="space-y-5">
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Description</label>
                                <input type="text" name="description" value="${escHtml(expense ? expense.description : '')}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="e.g. Lunch, MRT card top-up…" required>
                            </div>
                            <div class="grid grid-cols-2 gap-4">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Amount (NTD)</label>
                                    <input type="number" name="amount" value="${expense ? Number(expense.amount) : ''}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="0" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Date</label>
                                    <input type="date" name="date" value="${escHtml(expense ? expense.date : localYMD())}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Category</label>
                                <select name="expense_type" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium appearance-none">
                                    <option value="daily" ${!expense || expense.expense_type==='daily' ? 'selected':''}>Daily (food, transport…)</option>
                                    <option value="bills" ${expense?.expense_type==='bills' ? 'selected':''}>Fixed Bills</option>
                                    <option value="work" ${expense?.expense_type==='work' ? 'selected':''}>Work-related</option>
                                    <option value="one-time" ${expense?.expense_type==='one-time' ? 'selected':''}>One-time Purchase</option>
                                </select>
                            </div>
                            <div>
                                <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Tags <span class="normal-case font-normal">(comma-separated, e.g. food, mrt, rent)</span></label>
                                <input type="text" name="tags_raw" value="${escHtml(existingTags)}" id="tagsInput" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="food, transport, coffee…" oninput="window.renderTagPreview(this.value)">
                                <div id="tag-preview" class="flex flex-wrap gap-2 mt-2 min-h-[24px]"></div>
                            </div>
                            <div class="flex gap-4 mt-8">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg">${expense ? 'Update' : 'Add Expense'}</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;

            // Render initial tag preview
            if (existingTags) window.renderTagPreview(existingTags);

            document.getElementById('expenseForm').onsubmit = async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                const tagsRaw = fd.get('tags_raw') || '';
                const tags = tagsRaw.split(',').map(t => t.trim()).filter(Boolean);
                const payload = {
                    description: fd.get('description'),
                    amount: fd.get('amount'),
                    date: fd.get('date'),
                    expense_type: fd.get('expense_type'),
                    tags
                };
                const url = expense ? `/api/expenses/${expense.id}` : '/api/expenses';
                const method = expense ? 'PUT' : 'POST';
                const res = await fetch(url, {
                    method, headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                if (res.ok) { await fetchData(); render(); }
                else { const err = await res.json(); alert('Error: ' + (err.error || 'Unknown')); }
            };
        };

        window.showBudgetModal = () => {
            const month = state.selectedMonth;
            const typeConfig = {
                'daily':    { label: 'Daily',      color: '#3b82f6', icon: 'coffee'       },
                'bills':    { label: 'Bills',       color: '#8b5cf6', icon: 'file-text'    },
                'work':     { label: 'Work',        color: '#f59e0b', icon: 'briefcase'    },
                'one-time': { label: 'One-time',    color: '#ec4899', icon: 'shopping-bag' }
            };
            const monthBudgets = {};
            state.expenseBudgets
                .filter(b => b.month === month)
                .forEach(b => { monthBudgets[b.expense_type] = b; });
            const modal = document.getElementById('expense-modal-container');
            modal.innerHTML = `
                <div class="fixed inset-0 bg-zinc-900/40 backdrop-blur-md flex items-center justify-center z-50 p-4">
                    <div class="bg-white p-10 rounded-[2.5rem] shadow-2xl w-full max-w-md border border-black/5 animate-slide relative overflow-hidden">
                        <div class="absolute top-0 left-0 w-full h-2 bg-amber-400"></div>
                        <h3 class="text-3xl font-extrabold mb-2 tracking-tight">Monthly Budgets</h3>
                        <p class="text-sm text-zinc-400 font-medium mb-8">Spending limits for ${escHtml(month)}. Leave blank to remove a limit.</p>
                        <form id="budgetForm" class="space-y-5">
                            ${Object.entries(typeConfig).map(([type, cfg]) => `
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">${escHtml(cfg.label)}</label>
                                    <input type="number" min="0" step="any" name="budget_${type}" value="${monthBudgets[type] ? Number(monthBudgets[type].limit_amount) : ''}" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" placeholder="No limit">
                                </div>
                            `).join('')}
                            <div class="flex gap-4 mt-8">
                                <button type="button" onclick="this.closest('.fixed').remove()" class="flex-1 py-4 border border-zinc-100 rounded-2xl font-bold text-zinc-400 hover:bg-zinc-50 transition-all">Cancel</button>
                                <button type="submit" class="flex-1 py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all shadow-lg">Save Budgets</button>
                            </div>
                        </form>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('budgetForm').onsubmit = async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                let saveError = null;
                const failed = [];
                try {
                    for (const type of Object.keys(typeConfig)) {
                        const raw = (fd.get(`budget_${type}`) || '').toString().trim();
                        const existing = monthBudgets[type];
                        if (raw === '') {
                            if (existing) {
                                const res = await fetch(`/api/expenses/budgets/${existing.id}`, { method: 'DELETE' });
                                if (!res.ok) failed.push(typeConfig[type].label);
                            }
                            continue;
                        }
                        const res = await fetch('/api/expenses/budgets', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ month, expense_type: type, limit_amount: raw })
                        });
                        if (!res.ok) failed.push(typeConfig[type].label);
                    }
                } catch (err) {
                    saveError = 'Network error';
                }
                try {
                    await fetchData();
                    render();
                } catch (err) {
                    saveError = saveError || 'Saved, but refresh failed';
                }
                if (saveError) {
                    alert('Error: ' + saveError);
                } else if (failed.length) {
                    alert('Error: could not save budgets for ' + failed.join(', '));
                } else {
                    showToast('Budgets saved');
                }
            };
        };

        window.renderTagPreview = (value) => {
            const tags = value.split(',').map(t => t.trim()).filter(Boolean);
            const preview = document.getElementById('tag-preview');
            if (!preview) return;
            preview.innerHTML = tags.map(t =>
                `<span class="px-3 py-1 bg-zinc-100 rounded-full text-[10px] font-bold text-zinc-600">#${escHtml(t)}</span>`
            ).join('');
        };

        window.deleteExpense = async (id) => {
            if (confirm('Delete this expense?')) {
                await fetch(`/api/expenses/${id}`, { method: 'DELETE' });
                await fetchData();
                render();
            }
        };

        async function renderProfile(container) {
            container.innerHTML = '<div class="flex items-center justify-center py-20"><div class="animate-spin rounded-full h-10 w-10 border-b-2 border-zinc-900"></div></div>';
            let profile = {
                username: state.user.username,
                role: state.user.role,
                stats: { jobs_count: state.jobs.length, income_records_count: state.income.length, expenses_count: state.expenses.length, notes_count: 0 }
            };
            try {
                const res = await fetch('/api/auth/profile');
                if (res.ok) profile = await res.json();
            } catch (e) {}

            container.innerHTML = `
                <div class="max-w-4xl mx-auto space-y-8 animate-slide">
                    <div>
                        <h2 class="text-3xl font-extrabold tracking-tight">Account & Profile</h2>
                        <p class="text-zinc-400 font-medium mt-1">Manage your username and password.</p>
                    </div>

                    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div class="bg-white p-6 rounded-3xl card-shadow border border-black/5">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">Jobs</p>
                            <p class="text-2xl font-extrabold mt-2">${Number(profile.stats?.jobs_count || 0)}</p>
                        </div>
                        <div class="bg-white p-6 rounded-3xl card-shadow border border-black/5">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">Income Logs</p>
                            <p class="text-2xl font-extrabold mt-2">${Number(profile.stats?.income_records_count || 0)}</p>
                        </div>
                        <div class="bg-white p-6 rounded-3xl card-shadow border border-black/5">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">Expenses</p>
                            <p class="text-2xl font-extrabold mt-2">${Number(profile.stats?.expenses_count || 0)}</p>
                        </div>
                        <div class="bg-white p-6 rounded-3xl card-shadow border border-black/5">
                            <p class="text-[10px] font-bold uppercase tracking-widest text-zinc-400">Notes</p>
                            <p class="text-2xl font-extrabold mt-2">${Number(profile.stats?.notes_count || 0)}</p>
                        </div>
                    </div>

                    <div class="grid grid-cols-1 md:grid-cols-2 gap-8">
                        <div class="bg-white p-8 rounded-[2.5rem] card-shadow border border-black/5">
                            <h3 class="text-xl font-extrabold mb-6">Profile Details</h3>
                            <form id="profileForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Username</label>
                                    <input type="text" name="username" value="${escAttr(profile.username)}" maxlength="80" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Role</label>
                                    <input type="text" value="${escAttr(profile.role)}" class="w-full p-4 rounded-2xl bg-zinc-100 border border-zinc-100 text-zinc-500 font-bold uppercase text-xs tracking-widest" disabled>
                                </div>
                                <button type="submit" class="w-full py-4 bg-zinc-900 text-white rounded-2xl font-bold hover:bg-zinc-800 transition-all">Save Profile</button>
                            </form>
                        </div>

                        <div class="bg-white p-8 rounded-[2.5rem] card-shadow border border-black/5">
                            <h3 class="text-xl font-extrabold mb-6">Change Password</h3>
                            <form id="changePasswordForm" class="space-y-5">
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Current Password</label>
                                    <input type="password" name="current_password" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">New Password</label>
                                    <input type="password" name="new_password" minlength="6" maxlength="72" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                                <div>
                                    <label class="block text-[10px] font-bold uppercase tracking-[0.2em] text-zinc-400 mb-2 ml-1">Confirm New Password</label>
                                    <input type="password" name="confirm_password" minlength="6" maxlength="72" class="w-full p-4 rounded-2xl bg-zinc-50 border border-zinc-100 focus:border-zinc-900 focus:bg-white outline-none transition-all font-medium" required>
                                </div>
                                <button type="submit" class="w-full py-4 bg-emerald-600 text-white rounded-2xl font-bold hover:bg-emerald-700 transition-all">Update Password</button>
                            </form>
                        </div>
                    </div>
                </div>
            `;
            lucide.createIcons();

            document.getElementById('profileForm').onsubmit = async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                const username = (fd.get('username') || '').trim();
                try {
                    const res = await fetch('/api/auth/profile', {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username })
                    });
                    const body = await res.json().catch(() => ({}));
                    if (res.ok) {
                        state.user.username = body.username;
                        showToast('Profile updated!');
                        render();
                    } else {
                        showToast(body.error || 'Could not update profile', 'error');
                    }
                } catch (err) {
                    showToast('Cannot reach the server. Please try again.', 'error');
                }
            };

            document.getElementById('changePasswordForm').onsubmit = async (e) => {
                e.preventDefault();
                const fd = new FormData(e.target);
                const current_password = fd.get('current_password');
                const new_password = fd.get('new_password');
                const confirm_password = fd.get('confirm_password');
                if (new_password !== confirm_password) {
                    showToast('New passwords do not match', 'error');
                    return;
                }
                try {
                    const res = await fetch('/api/auth/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ current_password, new_password })
                    });
                    const body = await res.json().catch(() => ({}));
                    if (res.ok) {
                        e.target.reset();
                        showToast('Password updated successfully!');
                    } else {
                        showToast(body.error || 'Could not update password', 'error');
                    }
                } catch (err) {
                    showToast('Cannot reach the server. Please try again.', 'error');
                }
            };
        }

        init();
