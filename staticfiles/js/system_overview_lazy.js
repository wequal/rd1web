// system_overview_lazy.js
// Dynamically fetches system counts and rows via new JSON API endpoints.

(function(){
    const SUMMARY_URL = '/api/systems/summary/';
    const CATEGORY_URL = cat => `/api/systems/${cat}/`;

    const pageState = {}; // {category: nextUrl|null}

    function qs(selector, scope=document){return scope.querySelector(selector);}   

    function updateCardCount(category, count){
        const map = {
            burnin: '#burninCount',
            dc: '#dcCount',
            ac: '#acCount',
            archive: '#archiveCount',
            other: '#otherCount'
        };
        const el = qs(map[category]);
        if(el) el.textContent = count;

        // Update tab label count, text inside parentheses
        const tabBtn = qs(`#${category}-tab`);
        if(tabBtn){
            const label = tabBtn.textContent;
            tabBtn.textContent = label.replace(/\(.*?\)/, `(${count})`);
        }
    }

    function fetchSummary(){
        fetch(SUMMARY_URL,{credentials:'include'})
            .then(r=>r.ok?r.json():null)
            .then(data=>{
                if(!data) return;
                Object.entries(data).forEach(([cat,count])=>updateCardCount(cat,count));
            })
            .catch(()=>{});
    }

    function buildRowHTML(system, category){
        const lastUpdated = system.last_updated ? new Date(system.last_updated).toLocaleString() : 'Never';
        const macDisplay = system.formatted_mac || system.mac;
        const sysName = system.folder_name;
        const bmc = system.sysconfig?.bmc_ip || 'N/A';
        const lan = system.sysconfig?.bootip || 'N/A';
        let row=`<tr class="system-row"><td class="ps-4">`+
            `<div class="d-flex align-items-center">`+
            `<div class="system-info">`+
            `<div class="system-name fw-bold">${macDisplay}</div>`+
            `<small class="text-muted">${sysName}</small>`+
            `</div></div></td>`;
        // Network info
        row+=`<td><div class="small"><div><strong>BMC:</strong> ${bmc}</div><div><strong>LAN:</strong> ${lan}</div></div></td>`;

        if(category==='burnin'){
            const current = system.current_test || 'None';
            row+=`<td>${current}</td>`;
            // simple status badge
            row+=`<td><span class="badge bg-secondary">${system.status}</span></td>`;
        } else if(category==='dc' || category==='ac'){
            // progress (if any)
            const progress = system.progress || 0;
            row+=`<td><div class="progress" style="width:100px;height:8px;"><div class="progress-bar bg-info" style="width:${progress}%"></div></div></td>`;
            row+=`<td><span class="badge bg-secondary">${system.status}</span></td>`;
        } else {
            row+=`<td><span class="badge bg-secondary">${system.status}</span></td>`;
        }
        row+=`<td>${lastUpdated}</td>`;
        // actions
        row+=`<td><div class="btn-group" role="group">`+
            `<a href="/systems/${system.folder_name}/" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye me-1"></i>Details</a>`+
            `<a href="/logs/${system.folder_name}/" class="btn btn-sm btn-outline-info"><i class="fas fa-file-alt me-1"></i>Logs</a>`+
            `</div></td></tr>`;
        return row;
    }

    function loadCategory(category){
        if(pageState[category]===false) return; // fully loaded
        const tableBody = qs(`#${category}Table tbody`);
        if(!tableBody) return;
        const url = pageState[category] || `${CATEGORY_URL(category)}?page_size=100`;
        // Show spinner row if empty
        if(!tableBody.children.length){
            tableBody.innerHTML='<tr><td colspan="6" class="text-center py-4"><div class="spinner-border" role="status"></div></td></tr>';
        }
        fetch(url,{credentials:'include'})
            .then(r=>r.ok?r.json():null)
            .then(data=>{
                if(!data) return;
                // Remove spinner if present
                tableBody.innerHTML=tableBody.innerHTML.replace(/<tr>.*spinner.*<\/tr>/,'');
                data.results.forEach(sys=>{
                    tableBody.insertAdjacentHTML('beforeend', buildRowHTML(sys, category));
                });
                if(data.next){
                    pageState[category]=data.next;
                    // Add load-more placeholder row
                    addLoadMoreRow(category, tableBody);
                } else {
                    pageState[category]=false; // fully loaded
                }
            })
            .catch(()=>{});
    }

    function addLoadMoreRow(category, body){
        // remove existing load more row
        const existing = body.querySelector('.load-more-row');
        if(existing) existing.remove();
        const row=document.createElement('tr');
        row.className='load-more-row';
        row.innerHTML=`<td colspan="6" class="text-center"><button class="btn btn-sm btn-outline-primary">Load More</button></td>`;
        row.querySelector('button').addEventListener('click',()=>{
            row.remove();
            loadCategory(category);
        });
        body.appendChild(row);
    }

    document.addEventListener('DOMContentLoaded', () => {
        fetchSummary();
        // Setup tab listeners
        const tabButtons = document.querySelectorAll('#systemTabs button[data-bs-toggle="pill"]');
        tabButtons.forEach(btn=>{
            btn.addEventListener('shown.bs.tab', e=>{
                const targetId = btn.getAttribute('data-bs-target');
                const cat = targetId.replace('#','').replace('Tab','').toLowerCase();
                if(!pageState.hasOwnProperty(cat)){
                    loadCategory(cat);
                }
            });
        });
        // Initially load active tab (burnin)
        loadCategory('burnin');

        // ------------------------------------------------------------------
        // Auto-refresh every 60 seconds: update summary cards and the active tab
        // ------------------------------------------------------------------
        setInterval(()=>{
            fetchSummary();

            const activePane = document.querySelector('.tab-pane.show.active');
            if(!activePane) return;
            const activeCat = activePane.id.replace('Tab','').toLowerCase();
            // Reset pagination state so we reload from scratch
            pageState[activeCat] = undefined;
            const body = qs(`#${activeCat}Table tbody`);
            if(body){
                body.innerHTML = '';
                loadCategory(activeCat);
            }
        }, 60000); // 60 000 ms = 60 s
    });
})(); 