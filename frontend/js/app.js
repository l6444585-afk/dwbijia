const { createApp, ref, watch, nextTick } = Vue;

createApp({
    setup() {
        // 搜索状态
        const keyword = ref('');
        const loading = ref(false);
        const result = ref(null);
        const activeTab = ref('matched');
        const hotTags = ref(['Nike Air Force 1', 'AJ1', 'Adidas Yeezy', '匡威1970s', 'New Balance 574']);

        // 用户状态
        const user = ref(null);
        const token = ref(localStorage.getItem('token') || '');
        const showLogin = ref(false);
        const showFavorites = ref(false);
        const isRegister = ref(false);
        const authError = ref('');
        const loginForm = ref({ username: '', email: '', password: '' });

        // 图表实例
        let priceChartInstance = null;
        let distChartInstance = null;
        let pieChartInstance = null;

        // 初始化 - 检查登录状态
        if (token.value) {
            fetchUser();
        }

        // === API 调用 ===
        function apiHeaders() {
            const h = { 'Content-Type': 'application/json' };
            if (token.value) h['Authorization'] = `Bearer ${token.value}`;
            return h;
        }

        async function search() {
            if (!keyword.value.trim()) return;
            loading.value = true;
            result.value = null;

            try {
                const resp = await fetch(`/api/products/search?keyword=${encodeURIComponent(keyword.value)}&page=1&page_size=10`);
                const data = await resp.json();
                result.value = data;
                activeTab.value = 'matched';
            } catch (e) {
                console.error('搜索失败:', e);
            } finally {
                loading.value = false;
            }
        }

        async function fetchUser() {
            try {
                const resp = await fetch('/api/users/me', { headers: apiHeaders() });
                if (resp.ok) {
                    user.value = await resp.json();
                } else {
                    token.value = '';
                    localStorage.removeItem('token');
                }
            } catch (e) {
                console.error('获取用户失败:', e);
            }
        }

        async function handleAuth() {
            authError.value = '';
            const url = isRegister.value ? '/api/users/register' : '/api/users/login';
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(loginForm.value),
                });
                const data = await resp.json();
                if (data.token) {
                    token.value = data.token;
                    localStorage.setItem('token', data.token);
                    user.value = data.user;
                    showLogin.value = false;
                    loginForm.value = { username: '', email: '', password: '' };
                } else {
                    authError.value = data.detail || '操作失败';
                }
            } catch (e) {
                authError.value = '网络错误';
            }
        }

        function logout() {
            user.value = null;
            token.value = '';
            localStorage.removeItem('token');
        }

        // === 图表渲染 ===
        watch(activeTab, async (tab) => {
            if (tab === 'chart' && result.value) {
                await nextTick();
                renderCharts();
            }
        });

        function renderCharts() {
            const r = result.value;
            if (!r) return;

            // 销毁旧图表
            if (priceChartInstance) priceChartInstance.destroy();
            if (distChartInstance) distChartInstance.destroy();
            if (pieChartInstance) pieChartInstance.destroy();

            // 价格对比柱状图
            const tbItems = r.taobao.items.slice(0, 8);
            const dwItems = r.dewu.items.slice(0, 8);
            const labels = tbItems.map((_, i) => `商品${i + 1}`);

            const ctx1 = document.getElementById('priceChart');
            if (ctx1) {
                priceChartInstance = new Chart(ctx1, {
                    type: 'bar',
                    data: {
                        labels,
                        datasets: [
                            {
                                label: '淘宝价格',
                                data: tbItems.map(i => i.price),
                                backgroundColor: 'rgba(255, 68, 0, 0.7)',
                                borderRadius: 4,
                            },
                            {
                                label: '得物价格',
                                data: dwItems.map(i => i.price),
                                backgroundColor: 'rgba(0, 200, 170, 0.7)',
                                borderRadius: 4,
                            },
                        ],
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { position: 'top' },
                        },
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: '价格 (¥)' } },
                        },
                    },
                });
            }

            // 价格区间分布
            const ranges = ['0-200', '200-500', '500-1000', '1000-2000', '2000+'];
            const tbDist = [0, 0, 0, 0, 0];
            const dwDist = [0, 0, 0, 0, 0];

            r.taobao.items.forEach(i => {
                if (i.price < 200) tbDist[0]++;
                else if (i.price < 500) tbDist[1]++;
                else if (i.price < 1000) tbDist[2]++;
                else if (i.price < 2000) tbDist[3]++;
                else tbDist[4]++;
            });
            r.dewu.items.forEach(i => {
                if (i.price < 200) dwDist[0]++;
                else if (i.price < 500) dwDist[1]++;
                else if (i.price < 1000) dwDist[2]++;
                else if (i.price < 2000) dwDist[3]++;
                else dwDist[4]++;
            });

            const ctx2 = document.getElementById('distributionChart');
            if (ctx2) {
                distChartInstance = new Chart(ctx2, {
                    type: 'line',
                    data: {
                        labels: ranges,
                        datasets: [
                            {
                                label: '淘宝',
                                data: tbDist,
                                borderColor: '#FF4400',
                                backgroundColor: 'rgba(255,68,0,0.1)',
                                fill: true,
                                tension: 0.3,
                            },
                            {
                                label: '得物',
                                data: dwDist,
                                borderColor: '#00C8AA',
                                backgroundColor: 'rgba(0,200,170,0.1)',
                                fill: true,
                                tension: 0.3,
                            },
                        ],
                    },
                    options: { responsive: true, plugins: { legend: { position: 'top' } } },
                });
            }

            // 平台优势饼图
            const ctx3 = document.getElementById('pieChart');
            if (ctx3) {
                pieChartInstance = new Chart(ctx3, {
                    type: 'doughnut',
                    data: {
                        labels: ['淘宝更便宜', '得物更便宜', '价格相同'],
                        datasets: [{
                            data: [
                                r.stats.taobao_cheaper_count,
                                r.stats.dewu_cheaper_count,
                                r.stats.matched_count - r.stats.taobao_cheaper_count - r.stats.dewu_cheaper_count,
                            ],
                            backgroundColor: ['#FF4400', '#00C8AA', '#d1d5db'],
                        }],
                    },
                    options: {
                        responsive: true,
                        plugins: {
                            legend: { position: 'bottom' },
                        },
                    },
                });
            }
        }

        return {
            keyword, loading, result, activeTab, hotTags,
            user, showLogin, showFavorites, isRegister, authError, loginForm,
            search, handleAuth, logout,
        };
    },
}).mount('#app');
