/**
 * FoodRescue AI — SaaS Operational Control Center Client Application
 * Handles live synchronization with Agent Kernel, WhatsApp messages, Leaflet map,
 * multi-tab navigation, modals, and reactive polling.
 */

const App = (function () {
  // Global State
  const state = {
    activeTab: 'dashboard',
    activeSubTab: 'inventory',
    activeConversationPhone: null,
    pollingInterval: 4000,
    pollTimerSeconds: 4,
    timerIntervalId: null,
    pollIntervalId: null,
    map: null,
    mapMarkers: [],
    
    // Cached Data
    stats: {},
    liveOperations: [],
    donations: [],
    donors: [],
    organizations: [],
    volunteers: [],
    users: [],
    conversations: [],
    activeMessages: [],
    pickups: [],
    agentEvents: [],
    notifications: [],
    reports: {},
    settings: {},
  };

  // Header Titles & Descriptions Map
  const tabMetadata = {
    'dashboard': {
      title: 'Operational Dashboard',
      desc: 'Real-time surplus food coordination and WhatsApp integration overview.'
    },
    'live-operations': {
      title: 'Live Rescue Operations',
      desc: '7-step end-to-end operational pipeline from donor contact to delivery.'
    },
    'donations': {
      title: 'Donations & Donors Registry',
      desc: 'Real-time surplus inventory and registered food donor partners.'
    },
    'organizations': {
      title: 'Recipient Organizations',
      desc: 'Community kitchens, shelters, and food banks receiving donations.'
    },
    'volunteers': {
      title: 'Volunteer Courier Network',
      desc: 'On-demand delivery couriers, vehicle capacity, and availability.'
    },
    'users': {
      title: 'Persistent User Profiles',
      desc: 'WhatsApp normalized phone identities, language, and response modes.'
    },
    'conversations': {
      title: 'WhatsApp Conversations & Simulator',
      desc: 'Live two-way WhatsApp message threads and conversational memory.'
    },
    'pickups': {
      title: 'Pickup & Delivery Logistics',
      desc: 'Dispatch assignments, route mileage, and volunteer reimbursements.'
    },
    'map': {
      title: 'Operations Geographic Map',
      desc: 'Real-time operational map of donor pickups, hubs, and active couriers.'
    },
    'agent-activity': {
      title: 'Agent Kernel Audit Trail',
      desc: 'Audited log of autonomous AI decisions, tool calls, and match events.'
    },
    'notifications': {
      title: 'System Notifications Log',
      desc: 'Automated WhatsApp alerts and system communication dispatches.'
    },
    'reports': {
      title: 'Environmental & Social Impact Reports',
      desc: 'Key analytics on food saved, CO₂ prevented, and regional distribution.'
    },
    'settings': {
      title: 'Platform & Transport Settings',
      desc: 'Dynamic transport reimbursement rates and WhatsApp system health.'
    }
  };

  // Initialize Application
  async function init() {
    setupNavigation();
    setupMobileBottomNav();
    setupMobileSidebar();
    setupScrollProgress();
    setupScrollReveal();
    setupModals();
    
    // Initial Data Fetch
    await fetchAllData();

    // Start Real-Time Synchronizer Loop
    startSyncPolling();
  }

  // Navigation Setup
  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(button => {
      button.addEventListener('click', () => {
        const targetTab = button.getAttribute('data-tab');
        switchTab(targetTab);
      });
    });
  }

  function setupMobileBottomNav() {
    document.querySelectorAll('.bottom-nav-btn[data-tab]').forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        switchTab(targetTab);
      });
    });

    const moreToggle = document.getElementById('bnav-more-toggle');
    if (moreToggle) {
      moreToggle.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMobileSidebar();
      });
    }
  }

  function setupMobileSidebar() {
    const toggleBtn = document.getElementById('btn-mobile-sidebar');
    
    // Create backdrop if not present
    let backdrop = document.querySelector('.sidebar-backdrop');
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.className = 'sidebar-backdrop';
      document.body.appendChild(backdrop);
    }

    if (toggleBtn) {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMobileSidebar();
      });
    }

    backdrop.addEventListener('click', () => {
      closeMobileSidebar();
    });
  }

  function toggleMobileSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const backdrop = document.querySelector('.sidebar-backdrop');
    if (!sidebar) return;
    sidebar.classList.toggle('open');
    if (backdrop) {
      backdrop.classList.toggle('active', sidebar.classList.contains('open'));
    }
  }

  function closeMobileSidebar() {
    const sidebar = document.getElementById('app-sidebar');
    const backdrop = document.querySelector('.sidebar-backdrop');
    if (sidebar) sidebar.classList.remove('open');
    if (backdrop) backdrop.classList.remove('active');
  }

  function setupScrollProgress() {
    const progressBar = document.getElementById('scroll-progress-bar');
    if (!progressBar) return;

    window.addEventListener('scroll', () => {
      const winScroll = document.body.scrollTop || document.documentElement.scrollTop;
      const height = document.documentElement.scrollHeight - document.documentElement.clientHeight;
      const scrolled = height > 0 ? (winScroll / height) * 100 : 0;
      progressBar.style.width = scrolled + '%';
    }, { passive: true });
  }

  function setupScrollReveal() {
    if (!('IntersectionObserver' in window)) {
      document.querySelectorAll('.reveal-on-scroll').forEach(el => el.classList.add('is-visible'));
      return;
    }

    const observer = new IntersectionObserver((entries, obs) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          obs.unobserve(entry.target);
        }
      });
    }, {
      root: null,
      threshold: 0.08,
      rootMargin: '0px 0px -30px 0px'
    });

    document.querySelectorAll('.reveal-on-scroll, .stat-card, .panel, .dashboard-col').forEach(el => {
      el.classList.add('reveal-on-scroll');
      observer.observe(el);
    });
  }

  function switchTab(tabId) {
    if (!tabMetadata[tabId]) return;

    state.activeTab = tabId;

    // Update Nav Buttons
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });

    // Update Mobile Bottom Nav Buttons
    document.querySelectorAll('.bottom-nav-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
    });

    // Update Tab Views
    document.querySelectorAll('.tab-view').forEach(view => {
      view.classList.toggle('active', view.id === `view-${tabId}`);
    });

    // Update Header Text
    const meta = tabMetadata[tabId];
    document.getElementById('page-header-title').textContent = meta.title;
    document.getElementById('page-header-desc').textContent = meta.desc;

    // Close mobile sidebar if open
    closeMobileSidebar();

    // Smooth scroll to top of content
    window.scrollTo({ top: 0, behavior: 'smooth' });

    // Trigger tab-specific refresh/render
    renderCurrentTab();

    // Re-trigger scroll reveal for newly rendered view
    setTimeout(() => {
      setupScrollReveal();
    }, 60);

    // Leaflet map resize trigger when switching to Map tab
    if (tabId === 'map') {
      setTimeout(() => {
        initOrUpdateMap();
      }, 100);
    }
  }

  function renderCurrentTab() {
    switch (state.activeTab) {
      case 'dashboard':
        renderDashboard();
        break;
      case 'live-operations':
        renderLiveOperations();
        break;
      case 'donations':
        renderDonations();
        renderDonors();
        break;
      case 'organizations':
        renderOrganizations();
        break;
      case 'volunteers':
        renderVolunteers();
        break;
      case 'users':
        renderUsers();
        break;
      case 'conversations':
        renderConversations();
        break;
      case 'pickups':
        renderPickups();
        break;
      case 'map':
        initOrUpdateMap();
        break;
      case 'agent-activity':
        renderAgentEvents();
        break;
      case 'notifications':
        renderNotifications();
        break;
      case 'reports':
        renderReports();
        break;
      case 'settings':
        renderSettings();
        break;
    }
  }

  // Data Fetchers
  async function fetchAllData() {
    try {
      const [
        statsRes,
        opsRes,
        donsRes,
        donorsRes,
        orgsRes,
        volsRes,
        usersRes,
        convsRes,
        pickupsRes,
        eventsRes,
        notifsRes,
        reportsRes,
        settingsRes
      ] = await Promise.all([
        fetch('/api/dashboard').then(r => r.json()),
        fetch('/api/live-operations').then(r => r.json()),
        fetch('/api/donations').then(r => r.json()),
        fetch('/api/donors').then(r => r.json()),
        fetch('/api/organizations').then(r => r.json()),
        fetch('/api/volunteers').then(r => r.json()),
        fetch('/api/users').then(r => r.json()),
        fetch('/api/conversations').then(r => r.json()),
        fetch('/api/pickups').then(r => r.json()),
        fetch('/api/agent-events').then(r => r.json()),
        fetch('/api/notifications').then(r => r.json()),
        fetch('/api/reports').then(r => r.json()),
        fetch('/api/settings').then(r => r.json())
      ]);

      if (statsRes.stats) state.stats = statsRes.stats;
      if (opsRes.operations) state.liveOperations = opsRes.operations;
      if (donsRes.donations) state.donations = donsRes.donations;
      if (donorsRes.donors) state.donors = donorsRes.donors;
      if (orgsRes.organizations) state.organizations = orgsRes.organizations;
      if (volsRes.volunteers) state.volunteers = volsRes.volunteers;
      if (usersRes.users) state.users = usersRes.users;
      if (convsRes.conversations) state.conversations = convsRes.conversations;
      if (pickupsRes.pickups) state.pickups = pickupsRes.pickups;
      if (eventsRes.events) state.agentEvents = eventsRes.events;
      if (notifsRes.notifications) state.notifications = notifsRes.notifications;
      if (reportsRes) state.reports = reportsRes;
      if (settingsRes) state.settings = settingsRes;

      updateBadges();
      renderCurrentTab();
    } catch (err) {
      console.warn('Sync polling network notice:', err);
    }
  }

  // Polling Synchronizer
  function startSyncPolling() {
    if (state.pollIntervalId) clearInterval(state.pollIntervalId);
    if (state.timerIntervalId) clearInterval(state.timerIntervalId);

    state.pollTimerSeconds = 4;
    const timerElem = document.getElementById('sync-timer');

    state.timerIntervalId = setInterval(() => {
      state.pollTimerSeconds -= 1;
      if (state.pollTimerSeconds <= 0) {
        state.pollTimerSeconds = 4;
      }
      if (timerElem) timerElem.textContent = `${state.pollTimerSeconds}s`;
    }, 1000);

    state.pollIntervalId = setInterval(async () => {
      await fetchAllData();
      // If currently viewing active conversation, refresh messages too
      if (state.activeTab === 'conversations' && state.activeConversationPhone) {
        await loadConversationMessages(state.activeConversationPhone, false);
      }
    }, state.pollingInterval);
  }

  function updateBadges() {
    const s = state.stats;
    setText('badge-live-ops-count', (state.liveOperations || []).filter(o => o.status !== 'COMPLETED').length);
    setText('badge-donations-count', (state.donations || []).length);
    setText('badge-orgs-count', (state.organizations || []).length);
    setText('badge-vols-count', (state.volunteers || []).length);
    setText('badge-users-count', (state.users || []).length);
  }

  // 1. Render Dashboard View
  function renderDashboard() {
    const s = state.stats || {};
    setText('kpi-total-donations', s.total_donations || state.donations.length || 0);
    setText('kpi-available-donations', s.available_donations || 0);
    setText('kpi-active-pickups', s.active_pickups || 0);
    setText('kpi-completed-rescues', s.completed_deliveries || 0);
    setText('kpi-avail-vols', s.available_volunteers || 0);
    setText('kpi-total-orgs', s.registered_organizations || (state.organizations ? state.organizations.length : 0));
    const userCount = (s.active_users !== undefined && s.active_users !== null) ? s.active_users : ((state.users || []).length);
    setText('kpi-active-users', userCount);
    setText('kpi-co2-saved', `${s.co2_saved_kg || 0} kg`);

    // Render Active Rescue Pulse List
    const opsListElem = document.getElementById('dashboard-active-ops-list');
    const activeOps = (state.liveOperations || []).filter(o => o.status !== 'COMPLETED' && o.status !== 'CANCELLED');

    if (!activeOps || activeOps.length === 0) {
      opsListElem.innerHTML = '<div class="empty-state">No food rescues currently in transit. All surplus distributed!</div>';
    } else {
      opsListElem.innerHTML = activeOps.slice(0, 5).map(op => `
        <div class="op-item">
          <div class="op-info">
            <div class="op-title">
              <span>${escapeHtml(op.food_type)} (${op.quantity} ${op.unit})</span>
              <span class="badge badge-${op.stage_badge}">${op.stage_label}</span>
            </div>
            <div class="op-sub">
              📍 ${escapeHtml(op.pickup_location)} &rarr; ${escapeHtml(op.delivery_location)} • Courier: <strong>${escapeHtml(op.volunteer_name)}</strong>
            </div>
          </div>
          <button class="btn btn-secondary btn-sm" onclick="App.switchTab('live-operations')">Track</button>
        </div>
      `).join('');
    }

    // Render Activity Feed
    const feedElem = document.getElementById('dashboard-activity-feed');
    const events = (state.agentEvents || []).slice(0, 8);

    if (!events || events.length === 0) {
      feedElem.innerHTML = '<div class="empty-state">No recent Agent Kernel activity recorded.</div>';
    } else {
      feedElem.innerHTML = events.map(ev => `
        <div class="activity-item">
          <div class="activity-icon">⚡</div>
          <div class="activity-content">
            <div class="activity-title">${escapeHtml(ev.event_type.replace(/_/g, ' '))}</div>
            <div class="activity-time">Actor: <strong>${escapeHtml(ev.actor || 'Agent Kernel')}</strong> • ${formatDate(ev.created_at)}</div>
          </div>
        </div>
      `).join('');
    }
  }

  // 2. Render Live Operations Pipeline View
  function renderLiveOperations() {
    const filter = (document.getElementById('select-ops-filter') || {}).value || 'all';
    const grid = document.getElementById('live-operations-grid');
    let ops = state.liveOperations || [];

    if (filter === 'in_transit') ops = ops.filter(o => ['EN_ROUTE', 'COLLECTED', 'DELIVERING'].includes(o.status));
    else if (filter === 'available') ops = ops.filter(o => o.status === 'AVAILABLE');
    else if (filter === 'completed') ops = ops.filter(o => o.status === 'COMPLETED' || o.status === 'DELIVERED' || o.status === 'DISTRIBUTED');

    if (!ops || ops.length === 0) {
      grid.innerHTML = '<div class="empty-state">No operations match the selected filter.</div>';
      return;
    }

    grid.innerHTML = ops.map(op => {
      const step = op.stage_step || 1;
      return `
        <div class="live-op-card">
          <div class="op-card-header">
            <div>
              <div class="op-card-title">${escapeHtml(op.food_type)}</div>
              <div class="op-sub">Donation ID: <span class="font-mono">${op.donation_id}</span></div>
            </div>
            <span class="badge badge-${op.stage_badge}">${op.stage_label}</span>
          </div>

          <!-- 7-Step Visual Stepper -->
          <div class="pipeline-stepper">
            ${[1, 2, 3, 4, 5, 6, 7].map(sNum => {
              const isCompleted = (step >= 7 ? sNum <= 7 : sNum < step);
              const isActive = (step < 7 && sNum === step);
              const cls = isCompleted ? 'completed' : (isActive ? 'active' : '');
              const icon = isCompleted ? '✓' : sNum;
              return `<div class="stepper-step ${cls}">${icon}</div>`;
            }).join('')}
          </div>

          <div class="op-card-details">
            <div class="detail-k">Quantity:</div><div class="detail-v">${op.quantity} ${op.unit} (${op.dietary_info})</div>
            <div class="detail-k">Pickup Location:</div><div class="detail-v">${escapeHtml(op.pickup_location)}</div>
            <div class="detail-k">Recipient Org:</div><div class="detail-v">${escapeHtml(op.organization_name)}</div>
            <div class="detail-k">Assigned Courier:</div><div class="detail-v">${escapeHtml(op.volunteer_name)}</div>
            <div class="detail-k">Distance & Cost:</div><div class="detail-v">${op.estimated_distance_km} km • LKR ${op.estimated_transport_cost}</div>
            <div class="detail-k">Pickup QR:</div>
            <div class="detail-v" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              ${op.pickup_qr_status === 'VERIFIED' ? '<span class="badge badge-emerald">✅ QR Verified</span>' : (op.pickup_qr_token ? `<button class="btn btn-sm btn-secondary" style="padding:2px 8px; font-size:11px;" onclick="App.showQrModal('${op.pickup_qr_token}', 'PICKUP', '${escapeHtml(op.food_type)}')">📷 Show QR</button><a href="/verify/pickup/${op.pickup_qr_token}" target="_blank" class="badge badge-amber" style="text-decoration:none">Scan ↗</a>` : '<span class="badge badge-slate">Pending</span>')}
            </div>
            <div class="detail-k">Delivery QR:</div>
            <div class="detail-v" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              ${op.delivery_qr_status === 'VERIFIED' ? '<span class="badge badge-emerald">✅ QR Verified</span>' : (op.delivery_qr_token ? `<button class="btn btn-sm btn-secondary" style="padding:2px 8px; font-size:11px;" onclick="App.showQrModal('${op.delivery_qr_token}', 'DELIVERY', '${escapeHtml(op.food_type)}')">📷 Show QR</button><a href="/verify/delivery/${op.delivery_qr_token}" target="_blank" class="badge badge-blue" style="text-decoration:none">Delivery ↗</a>` : '<span class="badge badge-slate">Pending</span>')}
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // 3. Render Donations View
  function renderDonations() {
    const tbody = document.getElementById('donations-table-body');
    const dons = state.donations || [];

    if (!dons || dons.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No food donations recorded in database.</td></tr>';
      return;
    }

    tbody.innerHTML = dons.map(d => `
      <tr>
        <td class="font-mono"><strong>${d.id}</strong></td>
        <td><strong>${escapeHtml(d.food_type)}</strong><br><small class="text-muted">${escapeHtml(d.dietary_information || 'Standard')}</small></td>
        <td>${d.quantity} ${d.unit || 'portions'}</td>
        <td>${escapeHtml(d.pickup_location)}</td>
        <td>${escapeHtml(d.pickup_deadline || 'Before 8 PM')}</td>
        <td><span class="badge badge-${getDonationBadgeColor(d.status)}">${d.status}</span></td>
        <td>${escapeHtml(d.matched_organization_id ? 'Matched Partner' : 'Awaiting Match')}</td>
        <td>${escapeHtml(d.assigned_volunteer_id ? 'Assigned' : 'Awaiting Dispatch')}</td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="App.viewDonationDetail('${d.id}')">View</button>
        </td>
      </tr>
    `).join('');
  }

  function renderDonors() {
    const tbody = document.getElementById('donors-table-body');
    const donors = state.donors || [];

    if (!donors || donors.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No donors registered.</td></tr>';
      return;
    }

    tbody.innerHTML = donors.map(d => `
      <tr>
        <td class="font-mono">${d.id}</td>
        <td><strong>${escapeHtml(d.name)}</strong></td>
        <td class="font-mono">${escapeHtml(d.phone)}</td>
        <td>${escapeHtml(d.location)}</td>
        <td>${escapeHtml(d.organization_name || 'Individual')}</td>
        <td>${formatDate(d.created_at)}</td>
      </tr>
    `).join('');
  }

  function toggleDonationSubTab(subTab) {
    state.activeSubTab = subTab;
    document.getElementById('subtab-donations').classList.toggle('active', subTab === 'inventory');
    document.getElementById('subtab-donors').classList.toggle('active', subTab === 'donors');
    document.getElementById('subview-donations-inventory').classList.toggle('active', subTab === 'inventory');
    document.getElementById('subview-donations-donors').classList.toggle('active', subTab === 'donors');
  }

  function filterDonations() {
    const q = (document.getElementById('search-donations') || {}).value?.toLowerCase() || '';
    const st = (document.getElementById('filter-donation-status') || {}).value || 'all';

    const rows = document.querySelectorAll('#donations-table-body tr');
    rows.forEach(r => {
      const text = r.textContent.toLowerCase();
      const matchesQ = text.includes(q);
      const matchesSt = st === 'all' || text.includes(st.toLowerCase());
      r.style.display = matchesQ && matchesSt ? '' : 'none';
    });
  }

  // 4. Render Organizations View
  function renderOrganizations() {
    const grid = document.getElementById('organizations-grid');
    const orgs = state.organizations || [];

    if (!orgs || orgs.length === 0) {
      grid.innerHTML = '<div class="empty-state">No recipient organizations registered.</div>';
      return;
    }

    grid.innerHTML = orgs.map(o => `
      <div class="partner-card">
        <div class="card-top">
          <div class="card-title">${escapeHtml(o.name)}</div>
          <span class="badge badge-emerald">Active Hub</span>
        </div>
        <div class="card-body-text">
          📍 <strong>Location:</strong> ${escapeHtml(o.location)}<br>
          🍲 <strong>Accepted Food:</strong> ${escapeHtml(o.accepted_food_types)}<br>
          📦 <strong>Daily Capacity:</strong> ${escapeHtml(o.capacity)}<br>
          📞 <strong>Phone:</strong> <span class="font-mono">${escapeHtml(o.phone)}</span>
        </div>
      </div>
    `).join('');
  }

  function filterOrganizations() {
    const q = (document.getElementById('search-orgs') || {}).value?.toLowerCase() || '';
    document.querySelectorAll('#organizations-grid .partner-card').forEach(c => {
      c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  }

  // 5. Render Volunteers View
  function renderVolunteers() {
    const grid = document.getElementById('volunteers-grid');
    const vols = state.volunteers || [];

    if (!vols || vols.length === 0) {
      grid.innerHTML = '<div class="empty-state">No volunteer couriers registered.</div>';
      return;
    }

    grid.innerHTML = vols.map(v => `
      <div class="volunteer-card">
        <div class="card-top">
          <div class="card-title">🛵 ${escapeHtml(v.name)}</div>
          <span class="badge badge-${v.current_status === 'available' ? 'emerald' : 'amber'}">${v.current_status || 'Available'}</span>
        </div>
        <div class="card-body-text">
          📞 <strong>WhatsApp:</strong> <span class="font-mono">${escapeHtml(v.phone)}</span><br>
          📍 <strong>Service Area:</strong> ${escapeHtml(v.service_area)}<br>
          🚲 <strong>Transport:</strong> ${escapeHtml(v.transport_mode || 'Motorbike')}<br>
          📦 <strong>Completed Pickups:</strong> ${v.completed_pickups || 0}
        </div>
      </div>
    `).join('');
  }

  function filterVolunteers() {
    const q = (document.getElementById('search-volunteers') || {}).value?.toLowerCase() || '';
    document.querySelectorAll('#volunteers-grid .volunteer-card').forEach(c => {
      c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  }

  // 6. Render Users View
  function renderUsers() {
    const tbody = document.getElementById('users-table-body');
    const users = state.users || [];

    if (!users || users.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty-state">No persistent WhatsApp users found.</td></tr>';
      return;
    }

    tbody.innerHTML = users.map(u => {
      const langMap = { en: 'English', si: 'සිංහල (Sinhala)', ta: 'தமிழ் (Tamil)', ml: 'മലയാളം (Malayalam)' };
      const langLabel = langMap[u.preferred_language] || u.preferred_language || 'English';
      return `
        <tr>
          <td class="font-mono"><strong>${escapeHtml(u.phone_number)}</strong></td>
          <td>${escapeHtml(u.display_name || 'User')}</td>
          <td><span class="badge badge-slate">${u.user_role || 'Unassigned'}</span></td>
          <td><span class="badge badge-emerald">${langLabel}</span></td>
          <td><span class="badge badge-blue">${(u.preferred_response_mode || 'text').toUpperCase()}</span></td>
          <td>${u.onboarding_completed ? '✅ Completed' : '⏳ In Progress'}</td>
          <td>${u.active_draft && (u.active_draft.food_type || (u.active_draft.quantity && u.active_draft.quantity > 0)) ? '📝 Active Draft' : 'None'}</td>
          <td>${formatDate(u.last_seen_at)}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="App.openUserConversation('${u.phone_number}')">Open Chat</button>
          </td>
        </tr>
      `;
    }).join('');
  }

  function filterUsers() {
    const q = (document.getElementById('search-users') || {}).value?.toLowerCase() || '';
    const role = (document.getElementById('filter-user-role') || {}).value || 'all';

    document.querySelectorAll('#users-table-body tr').forEach(r => {
      const text = r.textContent.toLowerCase();
      const matchesQ = text.includes(q);
      const matchesRole = role === 'all' || text.includes(role.toLowerCase());
      r.style.display = matchesQ && matchesRole ? '' : 'none';
    });
  }

  // 7. Render Conversations View (WhatsApp Two-Pane Layout)
  function renderConversations() {
    const listElem = document.getElementById('conversations-threads-list');
    const convs = state.conversations || [];

    if (!convs || convs.length === 0) {
      listElem.innerHTML = '<div class="empty-state">No WhatsApp conversation history recorded yet.</div>';
      return;
    }

    listElem.innerHTML = convs.map(c => {
      const isSelected = state.activeConversationPhone === c.phone_number;
      return `
        <div class="thread-item ${isSelected ? 'active' : ''}" onclick="App.selectConversation('${c.phone_number}')">
          <div class="thread-avatar">💬</div>
          <div class="thread-info">
            <div class="thread-header-row">
              <span class="thread-name">${escapeHtml(c.display_name || c.phone_number)}</span>
              <span class="thread-time">${formatTimeShort(c.last_activity)}</span>
            </div>
            <div class="thread-snippet">
              ${c.last_message_is_voice ? '🎤 [Voice Note] ' : ''}${escapeHtml(c.last_message || 'Conversation initiated')}
            </div>
          </div>
        </div>
      `;
    }).join('');

    // If no active conversation selected, pick the first one
    if (!state.activeConversationPhone && convs.length > 0) {
      selectConversation(convs[0].phone_number);
    }
  }

  function openUserConversation(phone) {
    state.activeConversationPhone = phone;
    switchTab('conversations');
    selectConversation(phone);
  }

  async function selectConversation(phone) {
    state.activeConversationPhone = phone;

    // Highlight sidebar thread
    document.querySelectorAll('.thread-item').forEach(item => {
      item.classList.toggle('active', item.getAttribute('onclick')?.includes(phone));
    });

    await loadConversationMessages(phone, true);
  }

  function formatChatMessageContent(text) {
    if (!text) return '';

    // Check if message contains QR code token or image link
    const qrMatch = text.match(/\/api\/qr\/(FR-[A-Z0-9\-_]+)\.png/i) || text.match(/\/verify\/(pickup|delivery)\/(FR-[A-Z0-9\-_]+)/i);
    let qrCardHtml = '';

    if (qrMatch) {
      const token = qrMatch[1].startsWith('FR-') ? qrMatch[1] : qrMatch[2];
      const isPickup = token.toUpperCase().includes('-PK-');
      const verifUrl = `/verify/${isPickup ? 'pickup' : 'delivery'}/${token}`;
      const imgUrl = `/api/qr/${token}.png`;
      const title = isPickup ? '📦 Donor Pickup QR Code' : '🏢 Organization Delivery QR Code';

      qrCardHtml = `
        <div class="chat-qr-card">
          <div class="chat-qr-header">
            <span>${title}</span>
            <span class="badge ${isPickup ? 'badge-emerald' : 'badge-blue'}">${isPickup ? 'Pickup Proof' : 'Delivery Proof'}</span>
          </div>
          <div class="chat-qr-img-wrapper">
            <img src="${imgUrl}" alt="Handover QR Code" class="chat-qr-img" />
          </div>
          <a href="${verifUrl}" target="_blank" class="chat-qr-btn">
            <span>📱</span><span>Open Handover Verification Page ↗</span>
          </a>
        </div>
      `;
    }

    let escaped = escapeHtml(text);
    // Replace markdown bold **text** or *text*
    escaped = escaped.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/(^|[^*])\*([^*]+)\*/g, '$1<strong>$2</strong>');
    // Replace newlines
    escaped = escaped.replace(/\n/g, '<br>');
    // Replace markdown links [label](url)
    escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\s\)]+|\/[^\s\)]+)\)/g, '<a href="$2" target="_blank" style="color: #0284c7; text-decoration: underline; font-weight: 600;">$1</a>');
    // Replace plain URLs
    escaped = escaped.replace(/(^|[^"'])(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" style="color: #0284c7; text-decoration: underline;">$2</a>');

    return escaped + qrCardHtml;
  }

  async function loadConversationMessages(phone, scrollBottom = true) {
    try {
      const res = await fetch(`/api/conversations/${encodeURIComponent(phone)}/messages`).then(r => r.json());
      const msgs = res.messages || [];
      state.activeMessages = msgs;

      // Update Header Bar
      const user = res.user || (state.users || []).find(u => u.phone_number === phone) || {};
      setText('chat-active-name', user.display_name || `WhatsApp User ${phone.slice(-4)}`);
      setText('chat-active-sub', `WhatsApp Thread • ${phone}`);

      const langMap = { en: 'English', si: 'සිංහල', ta: 'தமிழ்', ml: 'മലയാളം' };
      setText('chat-badge-lang', langMap[user.preferred_language] || user.preferred_language || 'English');
      setText('chat-badge-mode', `${(user.preferred_response_mode || 'text').toUpperCase()} MODE`);

      const container = document.getElementById('chat-messages-container');

      if (!msgs || msgs.length === 0) {
        container.innerHTML = `
          <div class="empty-state">
            No messages exchanged yet with <strong>${phone}</strong>.<br>
            Use the input below to simulate an incoming WhatsApp message.
          </div>
        `;
        return;
      }

      container.innerHTML = msgs.map(m => {
        const isUser = m.sender === 'user';
        return `
          <div class="message-bubble ${isUser ? 'bubble-user' : 'bubble-agent'}">
            ${m.is_voice ? `<div class="voice-badge-tag">🎤 Voice Note (${m.transcript ? 'Transcribed' : 'Audio'})</div>` : ''}
            <div>${formatChatMessageContent(m.message_text)}</div>
            <div class="bubble-time">${formatTimeShort(m.timestamp)} ${isUser ? '<span class="wa-double-tick" style="color: #38bdf8; font-weight: 700; margin-left: 4px;" title="Read & Delivered">✓✓</span>' : ''}</div>
          </div>
        `;
      }).join('');

      if (scrollBottom) {
        container.scrollTop = container.scrollHeight;
      }
    } catch (err) {
      console.error('Failed to load conversation messages:', err);
    }
  }

  async function handleSendSimulatorMessage(e) {
    e.preventDefault();
    if (!state.activeConversationPhone) {
      alert('Please select a conversation thread first.');
      return;
    }

    const input = document.getElementById('composer-text-input');
    const isVoice = document.getElementById('composer-is-voice')?.checked || false;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';

    // Append optimistic user bubble
    const container = document.getElementById('chat-messages-container');
    container.innerHTML += `
      <div class="message-bubble bubble-user">
        ${isVoice ? '<div class="voice-badge-tag">🎤 Voice Note</div>' : ''}
        <div>${escapeHtml(text)}</div>
        <div class="bubble-time">Just now</div>
      </div>
    `;
    container.scrollTop = container.scrollHeight;

    try {
      const res = await fetch(`/api/conversations/${encodeURIComponent(state.activeConversationPhone)}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, is_voice: isVoice })
      }).then(r => r.json());

      if (res.status === 'success') {
        await loadConversationMessages(state.activeConversationPhone, true);
        await fetchAllData();
      }
    } catch (err) {
      console.error('Simulator message error:', err);
    }
  }

  function filterConversations() {
    const q = (document.getElementById('search-threads') || {}).value?.toLowerCase() || '';
    document.querySelectorAll('.thread-item').forEach(item => {
      item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  }

  // 8. Render Pickups & Reimbursements View
  function renderPickups() {
    const tbody = document.getElementById('pickups-table-body');
    const tasks = state.pickups || [];

    if (!tasks || tasks.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-state">No pickup tasks recorded.</td></tr>';
      return;
    }

    tbody.innerHTML = tasks.map(t => `
      <tr>
        <td class="font-mono"><strong>${t.id}</strong></td>
        <td class="font-mono">${t.donation_id}</td>
        <td>${escapeHtml(t.pickup_location)}</td>
        <td>${escapeHtml(t.delivery_location)}</td>
        <td><strong>${escapeHtml(t.volunteer_name || 'Awaiting')}</strong></td>
        <td><span class="badge badge-${getTaskBadgeColor(t.status)}">${t.status}</span></td>
        <td>${t.total_distance_km || 4.8} km</td>
        <td>LKR ${t.estimated_transport_cost || 350}</td>
        <td><span class="badge badge-slate">${t.approved_transport_reimbursement ? 'APPROVED' : 'PENDING'}</span></td>
        <td>
          <button class="btn btn-secondary btn-sm" onclick="App.approveReimbursement('${t.id}')">Approve</button>
        </td>
      </tr>
    `).join('');
  }

  function filterPickups() {
    const st = (document.getElementById('filter-pickups-status') || {}).value || 'all';
    document.querySelectorAll('#pickups-table-body tr').forEach(r => {
      const text = r.textContent;
      r.style.display = st === 'all' || text.includes(st) ? '' : 'none';
    });
  }

  async function approveReimbursement(taskId) {
    alert(`Reimbursement approved for Task ${taskId}.`);
  }

  // 9. Operations Map View (Leaflet Integration)
  function initOrUpdateMap() {
    const mapElem = document.getElementById('operations-leaflet-map');
    if (!mapElem || typeof L === 'undefined') return;

    if (!state.map) {
      state.map = L.map('operations-leaflet-map').setView([7.2520, 80.3464], 11);
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(state.map);
    }

    state.map.invalidateSize();

    // Fetch and render location markers
    fetch('/api/locations')
      .then(r => r.json())
      .then(data => {
        // Clear previous markers
        state.mapMarkers.forEach(m => state.map.removeLayer(m));
        state.mapMarkers = [];

        (data.markers || []).forEach(pin => {
          const marker = L.circleMarker([pin.latitude, pin.longitude], {
            radius: 8,
            fillColor: pin.type === 'organization' ? '#3b82f6' : (pin.type === 'volunteer' ? '#8b5cf6' : '#10b981'),
            color: '#ffffff',
            weight: 2,
            opacity: 1,
            fillOpacity: 0.9
          }).addTo(state.map);

          marker.bindPopup(`
            <div style="font-family: Inter, sans-serif; font-size: 13px;">
              <strong>${escapeHtml(pin.title)}</strong><br>
              <small style="color: #64748b;">${escapeHtml(pin.subtitle)}</small><br>
              <small>📍 ${escapeHtml(pin.location_name)}</small>
            </div>
          `);

          state.mapMarkers.push(marker);
        });

        if (state.mapMarkers.length > 0) {
          const group = L.featureGroup(state.mapMarkers);
          state.map.fitBounds(group.getBounds().pad(0.15));
        } else if (data.center && data.center.lat && data.center.lng) {
          state.map.setView([data.center.lat, data.center.lng], data.center.zoom || 11);
        }
      })
      .catch(err => console.warn('Map locations error:', err));
  }

  function drawPickupRoute(pickupLoc, deliveryLoc, volLoc) {
    if (!state.map || typeof L === 'undefined') return;
    
    // Clear previous route polylines
    (state.routeLayers || []).forEach(l => state.map.removeLayer(l));
    state.routeLayers = [];
    
    fetch('/api/routes/pickup-route', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        volunteer: volLoc || pickupLoc,
        donation: pickupLoc,
        organization: deliveryLoc,
        transport_mode: 'motorbike'
      })
    })
    .then(r => r.json())
    .then(data => {
      if (data.success && data.coordinates && data.coordinates.length > 0) {
        const latlngs = data.coordinates.map(pt => [pt[0], pt[1]]);
        const poly = L.polyline(latlngs, {
          color: '#10b981',
          weight: 5,
          opacity: 0.85,
          dashArray: '8, 8'
        }).addTo(state.map);
        
        state.routeLayers.push(poly);
        state.map.fitBounds(poly.getBounds(), {padding: [40, 40]});
      }
    })
    .catch(e => console.warn('GraphHopper pickup route draw error:', e));
  }

  // 10. Render Agent Activity (Audit Events) View
  function renderAgentEvents() {
    const tbody = document.getElementById('audit-events-table-body');
    const events = state.agentEvents || [];

    if (!events || events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No audit log records available.</td></tr>';
      return;
    }

    tbody.innerHTML = events.map(e => `
      <tr>
        <td class="font-mono">${formatDate(e.created_at)}</td>
        <td><strong>${escapeHtml(e.event_type.replace(/_/g, ' '))}</strong></td>
        <td><span class="badge badge-emerald">${escapeHtml(e.actor || 'Agent Kernel')}</span></td>
        <td class="font-mono">${escapeHtml(e.related_id || '—')}</td>
        <td class="font-mono text-muted" style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
          ${escapeHtml(JSON.stringify(e.metadata || {}))}
        </td>
      </tr>
    `).join('');
  }

  function filterAuditEvents() {
    const actor = (document.getElementById('filter-audit-actor') || {}).value || 'all';
    document.querySelectorAll('#audit-events-table-body tr').forEach(r => {
      r.style.display = actor === 'all' || r.textContent.includes(actor) ? '' : 'none';
    });
  }

  // 11. Render Notifications View
  function renderNotifications() {
    const tbody = document.getElementById('notifications-table-body');
    const notifs = state.notifications || [];

    if (!notifs || notifs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="empty-state">No notifications dispatched yet.</td></tr>';
      return;
    }

    tbody.innerHTML = notifs.map(n => `
      <tr>
        <td class="font-mono">${n.id}</td>
        <td><span class="badge badge-slate">${escapeHtml(n.recipient_type || 'user')}</span></td>
        <td class="font-mono">${escapeHtml(n.recipient_id || '')}</td>
        <td><span class="badge badge-emerald">WhatsApp</span></td>
        <td style="max-width: 350px;">${escapeHtml(n.message)}</td>
        <td><span class="badge badge-emerald">SENT</span></td>
        <td class="font-mono">${formatDate(n.created_at)}</td>
      </tr>
    `).join('');
  }

  // 12. Render Reports View
  function renderReports() {
    const rep = state.reports || {};
    const sum = rep.summary || {};

    const statsElem = document.getElementById('reports-impact-stats');
    if (statsElem) {
      statsElem.innerHTML = `
        <div class="impact-stat-box"><div class="impact-num">${sum.total_meals_rescued || 0}</div><div class="impact-label">Meals Rescued & Served</div></div>
        <div class="impact-stat-box"><div class="impact-num">${sum.total_food_kg || 0} kg</div><div class="impact-label">Surplus Food Saved</div></div>
        <div class="impact-stat-box"><div class="impact-num">${sum.co2_emissions_prevented_kg || 0} kg</div><div class="impact-label">CO₂ Offset Equivalent</div></div>
        <div class="impact-stat-box"><div class="impact-num">LKR ${(sum.financial_value_lkr || 0).toLocaleString()}</div><div class="impact-label">Economic Value Rescued</div></div>
      `;
    }

    const barsElem = document.getElementById('reports-regional-bars');
    if (barsElem) {
      const reg = rep.regional_distribution || { 'Colombo': 4, 'Dehiwala': 2, 'Kandy': 1 };
      const maxVal = Math.max(...Object.values(reg), 1);
      barsElem.innerHTML = Object.entries(reg).map(([region, count]) => `
        <div class="bar-row">
          <div class="bar-label-group"><span>${escapeHtml(region)}</span><span>${count} Rescues</span></div>
          <div class="bar-track"><div class="bar-fill" style="width: ${(count / maxVal) * 100}%;"></div></div>
        </div>
      `).join('');
    }

    const leaderboardElem = document.getElementById('reports-volunteer-leaderboard');
    if (leaderboardElem) {
      const vols = rep.volunteer_leaderboard || [];
      leaderboardElem.innerHTML = vols.map((v, i) => `
        <tr>
          <td><strong>#${i + 1}</strong></td>
          <td><strong>${escapeHtml(v.name)}</strong></td>
          <td>${escapeHtml(v.transport_mode)}</td>
          <td>${v.completed_pickups} deliveries</td>
          <td><span class="badge badge-emerald">${v.status}</span></td>
        </tr>
      `).join('');
    }
  }

  // 13. Render Settings View (Dynamic Vehicle Reimbursement Rate Manager)
  let localRatesByVehicle = {
    'Motorbike': 50.0,
    'Three-Wheeler': 90.0,
    'Car': 120.0,
    'Van': 150.0,
    'Bicycle': 25.0,
    'Electric Bike': 25.0
  };

  const VEHICLE_ICONS = {
    'Motorbike': '🛵',
    'Three-Wheeler': '🛺',
    'Car': '🚗',
    'Van': '🚐',
    'Bicycle': '🚲',
    'Electric Bike': '⚡',
    'Truck': '🚚'
  };

  function renderSettings() {
    const cfg = (state.settings || {}).transport_cost || {};
    if (cfg.base_fare !== undefined && document.getElementById('setting-base-fare')) {
      document.getElementById('setting-base-fare').value = cfg.base_fare;
    }
    if (cfg.cost_per_km !== undefined && document.getElementById('setting-cost-per-km')) {
      document.getElementById('setting-cost-per-km').value = cfg.cost_per_km;
    }
    if (cfg.currency && document.getElementById('setting-currency')) {
      document.getElementById('setting-currency').value = cfg.currency;
    }

    if (cfg.rates_by_vehicle && typeof cfg.rates_by_vehicle === 'object') {
      localRatesByVehicle = Object.assign({}, localRatesByVehicle, cfg.rates_by_vehicle);
    }

    handleVehicleSelectChange();
    renderVehicleRatesTable();
  }

  function handleVehicleSelectChange() {
    const selElem = document.getElementById('setting-vehicle-select');
    const inputElem = document.getElementById('setting-vehicle-rate-input');
    if (!selElem || !inputElem) return;
    const selectedMode = selElem.value;
    const currentRate = localRatesByVehicle[selectedMode] !== undefined ? localRatesByVehicle[selectedMode] : (selectedMode === 'Car' ? 120 : (selectedMode === 'Motorbike' ? 50 : 80));
    inputElem.value = currentRate;
  }

  function handleApplyVehicleRate() {
    const selElem = document.getElementById('setting-vehicle-select');
    const inputElem = document.getElementById('setting-vehicle-rate-input');
    if (!selElem || !inputElem) return;
    const selectedMode = selElem.value;
    const rateVal = parseFloat(inputElem.value);
    if (isNaN(rateVal) || rateVal < 0) {
      alert('Please enter a valid rate per kilometer.');
      return;
    }
    localRatesByVehicle[selectedMode] = rateVal;
    renderVehicleRatesTable();
  }

  function handleRemoveVehicleRate(mode) {
    if (localRatesByVehicle[mode] !== undefined) {
      delete localRatesByVehicle[mode];
      renderVehicleRatesTable();
    }
  }

  function renderVehicleRatesTable() {
    const tableElem = document.getElementById('settings-rates-table');
    if (!tableElem) return;

    const entries = Object.entries(localRatesByVehicle);
    if (entries.length === 0) {
      tableElem.innerHTML = '<div style="font-size: 0.85rem; color: var(--text-muted);">No vehicle rates defined. Default cost per km will apply.</div>';
      return;
    }

    tableElem.innerHTML = entries.map(([mode, rate]) => {
      const icon = VEHICLE_ICONS[mode] || '🚗';
      return `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.4rem 0.6rem; background: var(--bg-surface, #ffffff); border-radius: 6px; border: 1px solid var(--border-color, #e2e8f0);">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span style="font-size: 1.1rem;">${icon}</span>
            <strong style="font-size: 0.88rem;">${escapeHtml(mode)}</strong>
          </div>
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span class="badge badge-assigned" style="font-size: 0.85rem; font-family: monospace;">Rs. ${rate} / km</span>
            <button type="button" class="btn btn-ghost btn-sm" onclick="App.handleEditVehicleRate('${escapeHtml(mode)}')" style="padding: 2px 6px; font-size: 0.75rem;">Edit</button>
          </div>
        </div>
      `;
    }).join('');
  }

  function handleEditVehicleRate(mode) {
    const selElem = document.getElementById('setting-vehicle-select');
    const inputElem = document.getElementById('setting-vehicle-rate-input');
    if (selElem && inputElem && localRatesByVehicle[mode] !== undefined) {
      selElem.value = mode;
      inputElem.value = localRatesByVehicle[mode];
      inputElem.focus();
    }
  }

  async function handleSaveTransportSettings(e) {
    e.preventDefault();
    const baseFare = parseFloat(document.getElementById('setting-base-fare')?.value || 100);
    const costPerKm = parseFloat(document.getElementById('setting-cost-per-km')?.value || 80);

    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          base_fare: baseFare,
          cost_per_km: costPerKm,
          currency: 'LKR',
          rates_by_vehicle: localRatesByVehicle
        })
      }).then(r => r.json());

      if (res.status === 'success') {
        alert('Dynamic transport settings and vehicle reimbursement rates saved successfully!');
        await fetchAllData();
      } else {
        alert(res.message || 'Failed to update transport configuration.');
      }
    } catch (err) {
      alert('Failed to update transport configuration.');
    }
  }

  // Modals Setup
  function setupModals() {
    document.getElementById('btn-open-donation-modal')?.addEventListener('click', () => openModal('modal-new-donation'));
    document.getElementById('btn-open-volunteer-modal')?.addEventListener('click', () => openModal('modal-new-volunteer'));
    document.getElementById('btn-open-simulate-modal')?.addEventListener('click', () => openModal('modal-simulate-whatsapp'));
  }

  function openModal(id) {
    document.getElementById(id)?.classList.add('active');
  }

  function closeModal(id) {
    document.getElementById(id)?.classList.remove('active');
  }

  async function handleCreateDonation(e) {
    e.preventDefault();
    const food = document.getElementById('modal-don-food').value;
    const qty = parseFloat(document.getElementById('modal-don-qty').value);
    const unit = document.getElementById('modal-don-unit').value;
    const dietary = document.getElementById('modal-don-dietary').value;
    const loc = document.getElementById('modal-don-location').value;
    const donorName = document.getElementById('modal-don-donor-name').value;
    const donorPhone = document.getElementById('modal-don-donor-phone').value;
    const deadline = document.getElementById('modal-don-deadline').value;

    try {
      const res = await fetch('/api/donations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          food_type: food,
          quantity: qty,
          unit: unit,
          dietary_info: dietary,
          location: loc,
          donor_name: donorName,
          donor_phone: donorPhone,
          pickup_deadline: deadline
        })
      }).then(r => r.json());

      if (res.status === 'success') {
        closeModal('modal-new-donation');
        await fetchAllData();
        switchTab('donations');
      }
    } catch (err) {
      alert('Failed to create donation.');
    }
  }

  async function handleCreateVolunteer(e) {
    e.preventDefault();
    const name = document.getElementById('modal-vol-name').value;
    const phone = document.getElementById('modal-vol-phone').value;
    const transport = document.getElementById('modal-vol-transport').value;
    const area = document.getElementById('modal-vol-area').value;

    try {
      const res = await fetch('/api/volunteers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name,
          phone: phone,
          transport_mode: transport,
          service_area: area
        })
      }).then(r => r.json());

      if (res.status === 'success') {
        closeModal('modal-new-volunteer');
        await fetchAllData();
        switchTab('volunteers');
      }
    } catch (err) {
      alert('Failed to register courier.');
    }
  }

  async function handleTriggerSimulateModal(e) {
    e.preventDefault();
    const phone = document.getElementById('modal-sim-phone').value;
    const text = document.getElementById('modal-sim-text').value;
    const isVoice = document.getElementById('modal-sim-is-voice')?.checked || false;

    try {
      const res = await fetch(`/api/conversations/${encodeURIComponent(phone)}/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, is_voice: isVoice })
      }).then(r => r.json());

      if (res.status === 'success') {
        closeModal('modal-simulate-whatsapp');
        state.activeConversationPhone = phone;
        await fetchAllData();
        switchTab('conversations');
      }
    } catch (err) {
      alert('Failed to simulate message.');
    }
  }

  function setupMobileSidebar() {
    document.getElementById('btn-mobile-sidebar')?.addEventListener('click', () => {
      document.getElementById('app-sidebar').classList.toggle('open');
    });
  }

  // Utility Helpers
  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoStr;
    }
  }

  function formatTimeShort(isoStr) {
    if (!isoStr) return 'now';
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return 'now';
    }
  }

  function getDonationBadgeColor(status) {
    const map = {
      'AVAILABLE': 'emerald',
      'MATCHED': 'blue',
      'PICKUP_ASSIGNED': 'purple',
      'ASSIGNED': 'purple',
      'EN_ROUTE': 'blue',
      'COLLECTED': 'amber',
      'DELIVERED': 'emerald',
      'DISTRIBUTED': 'emerald',
      'COMPLETED': 'emerald',
      'CANCELLED': 'rose'
    };
    return map[status] || 'slate';
  }

  function getTaskBadgeColor(status) {
    const map = {
      'ASSIGNED': 'purple',
      'EN_ROUTE': 'blue',
      'COLLECTED': 'amber',
      'COMPLETED': 'emerald',
      'CANCELLED': 'rose'
    };
    return map[status] || 'slate';
  }

  async function handleResetAllData() {
    const confirmed = confirm(
      '⚠️ ARE YOU SURE?\n\nThis will permanently delete all temporary test data, donations, active pickups, recipient organizations, volunteers, users, and WhatsApp chat history.\n\nThe application will start completely fresh from 0.'
    );
    if (!confirmed) return;

    try {
      const res = await fetch('/api/reset-all', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      }).then(r => r.json());

      if (res.status === 'success') {
        alert('✅ Application database wiped cleanly. All counters and tables are reset to 0.');
        state.activeConversationPhone = null;
        await fetchAllData();
        switchTab('dashboard');
      } else {
        alert('Reset failed: ' + (res.detail || 'Unknown error'));
      }
    } catch (err) {
      alert('Failed to reset database.');
    }
  }

  function showQrModal(token, type, foodType) {
    const isPickup = (type || '').toUpperCase() === 'PICKUP' || token.toUpperCase().includes('-PK-');
    const title = isPickup ? '📦 Donor Pickup QR Code' : '🏢 Organization Delivery QR Code';
    const desc = isPickup
      ? `Display this Pickup QR code to the volunteer courier to verify physical handover of ${foodType || 'food donation'}.`
      : `Display this Delivery QR code to the volunteer courier to verify final delivery of ${foodType || 'food donation'}.`;

    setText('modal-qr-title', title);
    setText('modal-qr-desc', desc);
    const img = document.getElementById('modal-qr-img');
    if (img) img.src = `/api/qr/${token}.png`;
    const link = document.getElementById('modal-qr-link');
    if (link) link.href = `/verify/${isPickup ? 'pickup' : 'delivery'}/${token}`;

    openModal('modal-view-qr');
  }

  // Public Interface
  return {
    init,
    switchTab,
    toggleDonationSubTab,
    filterDonations,
    filterOrganizations,
    filterVolunteers,
    filterUsers,
    filterConversations,
    filterPickups,
    filterAuditEvents,
    selectConversation,
    openUserConversation,
    handleSendSimulatorMessage,
    handleSaveTransportSettings,
    handleVehicleSelectChange,
    handleApplyVehicleRate,
    handleEditVehicleRate,
    handleRemoveVehicleRate,
    handleCreateDonation,
    handleCreateVolunteer,
    handleTriggerSimulateModal,
    handleResetAllData,
    showQrModal,
    openModal,
    closeModal,
    approveReimbursement,
    drawPickupRoute,
    renderLiveOperations
  };
})();

// Bootstrap Application on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
