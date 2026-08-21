/**
 * FoodRescue AI — Frontend Web Application
 * Connects directly to Agent Kernel REST API (FastAPI backend).
 * Demonstrates:
 * 1. 7-Tab Navigation: Dashboard, AI Assistant, Donations, Organizations, Volunteers, Pickups, Session/Activity
 * 2. Multi-turn AI Coordination with Gemini via /api/v1/chat
 * 3. 7-Stage Visual Lifecycle Tracker: AVAILABLE -> MATCHED -> PICKUP PENDING -> PICKUP ASSIGNED -> EN ROUTE -> COLLECTED -> DELIVERED
 * 4. Real-time Dashboard KPIs & Live Backend Data
 * 5. Dedicated Organizations, Volunteers, and Pickups Logistics Board
 * 6. Multi-turn KeyValueCache Session Memory Inspector
 */

(function () {
  'use strict';

  // Application State
  const state = {
    sessionId: generateSessionId(),
    activeTab: 'dashboard',
    donations: [],
    activeDonationId: null,
    organizations: [],
    volunteers: [],
    pickups: [],
    reimbursements: [],
    notifications: [],
    stats: null,
    sessionContext: {},
    isChatThinking: false,
    autoRefreshInterval: null,
    activeGpsWatchId: null,
    activeGpsPickupId: null,
    lastGpsCoords: null,
  };

  // Helper to generate unique session ID
  function generateSessionId() {
    return 'session-' + Math.random().toString(36).substring(2, 9);
  }

  // Format Date Helper
  function formatTime(isoString) {
    if (!isoString) return 'Just now';
    try {
      const date = new Date(isoString);
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return isoString;
    }
  }

  function formatDate(isoString) {
    if (!isoString) return 'Today';
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + formatTime(isoString);
    } catch {
      return isoString;
    }
  }

  // Mask Phone Numbers for Public Privacy
  function maskPhone(phone) {
    if (!phone) return 'Verified (Private)';
    const clean = String(phone).trim();
    if (clean.length <= 6) return clean;
    return clean.substring(0, 6) + ' ****';
  }

  // UI Toast Notification System
  function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '✓';
    if (type === 'error') icon = '✕';
    if (type === 'info') icon = 'ℹ';

    toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(20px)';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // Escape HTML to prevent XSS
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Markdown simple parser for agent response
  function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    
    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    
    // Italic *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    
    // Inline code `code`
    html = html.replace(/`(.*?)`/g, '<code>$1</code>');
    
    // Bullet points * item
    html = html.replace(/^\s*\*\s+(.*)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
    
    // Line breaks
    html = html.replace(/\n\n/g, '<br><br>');
    html = html.replace(/\n/g, '<br>');

    return html;
  }

  // ==========================================
  // API CLIENT
  // ==========================================
  const API = {
    // 1. Health check
    async checkHealth() {
      try {
        const res = await fetch('/health');
        return res.ok;
      } catch {
        return false;
      }
    },

    // 2. Chat with FoodRescue Coordinator
    async sendChatPrompt(prompt, sessionId) {
      const res = await fetch('/api/v1/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent: 'foodrescue_coordinator',
          prompt: prompt,
          session_id: sessionId || state.sessionId,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Network error' }));
        throw new Error(err.detail?.error || err.detail || 'Chat request failed');
      }

      return await res.json();
    },

    // 3. Fetch Dashboard Stats
    async getStats() {
      const res = await fetch('/api/stats');
      if (!res.ok) throw new Error('Failed to fetch stats');
      return await res.json();
    },

    // 4. Fetch All Donations
    async getDonations(status = null) {
      let url = '/api/donations';
      if (status && status !== 'ALL') {
        url += `?status=${encodeURIComponent(status)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to fetch donations');
      return await res.json();
    },

    // 5. Fetch Single Donation Detail
    async getDonationDetail(donationId) {
      const res = await fetch(`/api/donations/${encodeURIComponent(donationId)}`);
      if (!res.ok) throw new Error('Failed to fetch donation detail');
      return await res.json();
    },

    // 6. Fetch Organizations
    async getOrganizations() {
      const res = await fetch('/api/organizations');
      if (!res.ok) throw new Error('Failed to fetch organizations');
      return await res.json();
    },

    // 7. Fetch Volunteers
    async getVolunteers() {
      const res = await fetch('/api/volunteers');
      if (!res.ok) throw new Error('Failed to fetch volunteers');
      return await res.json();
    },

    // 8. Fetch Pickups
    async getPickups() {
      const res = await fetch('/api/pickups');
      if (!res.ok) throw new Error('Failed to fetch pickups');
      return await res.json();
    },

    // 9. Fetch Notifications
    async getNotifications() {
      const res = await fetch('/api/notifications');
      if (!res.ok) throw new Error('Failed to fetch notifications');
      return await res.json();
    },

    // 10. Fetch Session Context
    async getSessionState(sessionId) {
      const res = await fetch(`/api/session-context/${encodeURIComponent(sessionId)}`);
      if (!res.ok) throw new Error('Failed to fetch session state');
      return await res.json();
    },

    // 11. Fetch Reimbursements
    async getReimbursements(status = null) {
      let url = '/api/reimbursements';
      if (status && status !== 'ALL') {
        url += `?status=${encodeURIComponent(status)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error('Failed to fetch reimbursements');
      return await res.json();
    },

    // 12. Update Reimbursement Status
    async updateReimbursementStatus(reimbId, status, notes = null) {
      const res = await fetch(`/api/reimbursements/${encodeURIComponent(reimbId)}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, notes }),
      });
      if (!res.ok) throw new Error('Failed to update reimbursement status');
      return await res.json();
    },

    // 13. Update Pickup Live GPS Location
    async updatePickupLocation(pickupId, latitude, longitude, accuracy_m = null, volunteer_id = null) {
      const res = await fetch(`/api/pickups/${encodeURIComponent(pickupId)}/location`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ latitude, longitude, accuracy_m, volunteer_id }),
      });
      if (!res.ok) throw new Error('Failed to send GPS location');
      return await res.json();
    },

    // 14. Calculate Route & Cost
    async calculateRoute(origin, destination, transport_mode = 'motorbike') {
      const res = await fetch('/api/routing/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ origin, destination, transport_mode }),
      });
      if (!res.ok) throw new Error('Failed to calculate route');
      return await res.json();
    },

    // 15. Create Volunteer Courier
    async createVolunteer(data) {
      const res = await fetch('/api/volunteers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to register volunteer courier');
      return await res.json();
    },

    // 16. Reset Demo Data
    async resetDemoData() {
      const res = await fetch('/api/reset-demo', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to reset demo data');
      return await res.json();
    },
  };

  // ==========================================
  // VIEW RENDERERS
  // ==========================================

  // 1. Render Dashboard
  function renderDashboard() {
    if (!state.stats) return;
    const stats = state.stats;

    // KPI Values
    const foodEl = document.getElementById('kpi-food-rescued');
    if (foodEl) foodEl.innerHTML = `${stats.total_food_quantity || 0} <span class="kpi-unit">meals/units</span>`;
    
    const donEl = document.getElementById('kpi-total-donations');
    if (donEl) donEl.textContent = stats.total_donations || 0;
    
    const activeEl = document.getElementById('kpi-active-rescues');
    if (activeEl) activeEl.textContent = stats.active_rescues || 0;
    
    const orgsEl = document.getElementById('kpi-total-orgs');
    if (orgsEl) orgsEl.textContent = stats.total_organizations || 0;
    
    const volsEl = document.getElementById('kpi-volunteers-ready');
    if (volsEl) volsEl.textContent = stats.available_volunteers || 0;
    
    const totalVolsEl = document.getElementById('kpi-total-volunteers');
    if (totalVolsEl) totalVolsEl.textContent = `${stats.total_volunteers || 0} registered`;
    
    const delivEl = document.getElementById('kpi-completed-deliveries');
    if (delivEl) delivEl.textContent = stats.delivered_rescues || 0;

    // Badges in navigation
    const badgeDon = document.getElementById('badge-donations-count');
    if (badgeDon) badgeDon.textContent = state.donations.length;
    
    const badgeOrg = document.getElementById('badge-organizations-count');
    if (badgeOrg) badgeOrg.textContent = state.organizations.length;
    
    const badgeVol = document.getElementById('badge-volunteers-count');
    if (badgeVol) badgeVol.textContent = state.volunteers.length;
    
    const badgePick = document.getElementById('badge-pickups-count');
    if (badgePick) badgePick.textContent = state.pickups.length;

    // Pipeline status distribution bars (All 7 Stages)
    const distContainer = document.getElementById('pipeline-status-bars');
    if (distContainer && stats.status_distribution) {
      const statuses = [
        { key: 'AVAILABLE', label: '1. AVAILABLE (New Donation)', color: 'var(--primary)' },
        { key: 'MATCHED', label: '2. MATCHED (Org Accepted)', color: 'var(--blue)' },
        { key: 'PICKUP_ASSIGNED', label: '3. PICKUP ASSIGNED (Volunteer Ready)', color: 'var(--purple)' },
        { key: 'EN_ROUTE', label: '4. EN ROUTE (Courier in Transit)', color: 'var(--cyan)' },
        { key: 'COLLECTED', label: '5. COLLECTED (Food Picked Up)', color: '#14B8A6' },
        { key: 'DELIVERED', label: '6. DELIVERED (Delivered to Org)', color: '#34D399' },
      ];

      const total = stats.total_donations || 1;
      let html = '';

      statuses.forEach((s) => {
        const count = stats.status_distribution[s.key] || 0;
        const pct = Math.round((count / total) * 100);
        html += `
          <div class="pipeline-row">
            <div class="pipeline-meta">
              <span class="pipeline-lbl">${s.label}</span>
              <span class="pipeline-num">${count} (${pct}%)</span>
            </div>
            <div class="pipeline-track">
              <div class="pipeline-fill" style="width: ${pct}%; background: ${s.color};"></div>
            </div>
          </div>
        `;
      });

      distContainer.innerHTML = html;
    }

    // Recent Donations Mini List
    const recentContainer = document.getElementById('recent-donations-container');
    if (recentContainer) {
      if (state.donations.length === 0) {
        recentContainer.innerHTML = `<div class="text-muted text-center py-4">No donations yet. Click "Report Donation" or chat with the AI Assistant.</div>`;
      } else {
        const recent = state.donations.slice(0, 4);
        recentContainer.innerHTML = recent
          .map(
            (d) => `
          <div class="mini-don-row" data-id="${d.id}">
            <div class="mini-don-left">
              <span class="mini-don-id">${escapeHtml(d.id)}</span>
              <div>
                <div class="mini-don-food">${d.quantity} ${escapeHtml(d.unit)} of ${escapeHtml(d.food_type)}</div>
                <div class="mini-don-loc">📍 ${escapeHtml(d.pickup_location)} • Available: ${escapeHtml(d.available_from)} - ${escapeHtml(d.pickup_deadline)}</div>
              </div>
            </div>
            <span class="status-badge status-${d.status}">${escapeHtml(d.status)}</span>
          </div>
        `
          )
          .join('');

        // Attach click to inspect donation
        recentContainer.querySelectorAll('.mini-don-row').forEach((row) => {
          row.addEventListener('click', () => {
            const donId = row.getAttribute('data-id');
            selectDonation(donId);
            switchTab('donations');
          });
        });
      }
    }

    // Notification Feed
    const notifsContainer = document.getElementById('notifications-stream');
    if (notifsContainer) {
      if (state.notifications.length === 0) {
        notifsContainer.innerHTML = `<div class="text-muted text-center py-4">No recent coordination events.</div>`;
      } else {
        notifsContainer.innerHTML = state.notifications
          .slice(0, 10)
          .map(
            (n) => `
          <div class="notif-item">
            <div class="notif-header">
              <span class="notif-badge badge-primary">${escapeHtml(n.recipient_type)}: ${escapeHtml(n.recipient_id)}</span>
              <span class="notif-time">${formatDate(n.created_at)}</span>
            </div>
            <div class="notif-msg">${escapeHtml(n.message)}</div>
          </div>
        `
          )
          .join('');
      }
    }
  }

  // 2. Render Donations Table & 7-Stage Stepper
  function renderDonations() {
    const tableBody = document.getElementById('donations-table-body');
    const badgeCounter = document.getElementById('badge-donations-count');
    if (badgeCounter) badgeCounter.textContent = state.donations.length;

    if (!tableBody) return;

    if (state.donations.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="8" class="text-center py-8 text-muted">No donation records found.</td></tr>`;
      return;
    }

    tableBody.innerHTML = state.donations
      .map((d) => {
        const isSelected = state.activeDonationId === d.id;
        return `
        <tr class="${isSelected ? 'active-row' : ''}">
          <td><code class="mini-don-id">${escapeHtml(d.id)}</code></td>
          <td><strong>${d.quantity} ${escapeHtml(d.unit)}</strong> ${escapeHtml(d.food_type)}</td>
          <td><span class="badge badge-subtle">${escapeHtml(d.dietary_information || 'Standard')}</span></td>
          <td>📍 ${escapeHtml(d.pickup_location)}</td>
          <td>${escapeHtml(d.available_from)} - ${escapeHtml(d.pickup_deadline)}</td>
          <td><span class="status-badge status-${d.status}">${escapeHtml(d.status)}</span></td>
          <td>${formatDate(d.created_at)}</td>
          <td>
            <button class="btn btn-secondary btn-sm btn-inspect-don" data-id="${d.id}">
              Track Lifecycle
            </button>
          </td>
        </tr>
      `;
      })
      .join('');

    // Attach inspect buttons
    tableBody.querySelectorAll('.btn-inspect-don').forEach((btn) => {
      btn.addEventListener('click', () => {
        const donId = btn.getAttribute('data-id');
        selectDonation(donId);
      });
    });

    // Update 7-Stage Stepper
    updateLifecycleStepper();
  }

  // Update 7-Stage Visual Lifecycle Stepper UI
  function updateLifecycleStepper() {
    const stepperTitle = document.getElementById('stepper-don-title');
    const actionContainer = document.getElementById('stepper-action-buttons');
    const nodes = document.querySelectorAll('#lifecycle-steps-bar .step-node');
    const lines = document.querySelectorAll('#lifecycle-steps-bar .step-line');

    if (!state.activeDonationId) {
      if (state.donations.length > 0) {
        state.activeDonationId = state.donations[0].id;
      } else {
        if (stepperTitle) stepperTitle.textContent = 'No active donations available to track.';
        if (actionContainer) actionContainer.innerHTML = '';
        return;
      }
    }

    const don = state.donations.find((d) => d.id === state.activeDonationId);
    if (!don) return;

    if (stepperTitle) {
      stepperTitle.innerHTML = `<strong>${escapeHtml(don.id)}</strong>: ${don.quantity} ${escapeHtml(don.unit)} of ${escapeHtml(don.food_type)} (Pickup: ${escapeHtml(don.pickup_location)}) — Status: <span class="status-badge status-${don.status}">${escapeHtml(don.status)}</span>`;
    }

    // 7 Exact Stages: AVAILABLE -> MATCHED -> PICKUP_PENDING -> PICKUP_ASSIGNED -> EN_ROUTE -> COLLECTED -> DELIVERED
    const stageOrder = [
      'AVAILABLE',
      'MATCHED',
      'PICKUP_PENDING',
      'PICKUP_ASSIGNED',
      'EN_ROUTE',
      'COLLECTED',
      'DELIVERED',
    ];

    const currentStatus = don.status;
    const currentIdx = stageOrder.indexOf(currentStatus);

    nodes.forEach((node, idx) => {
      const stageName = node.getAttribute('data-stage');
      const stageIdx = stageOrder.indexOf(stageName);

      node.classList.remove('completed', 'active');
      if (currentStatus === 'CANCELLED') {
        // cancelled state
      } else if (stageIdx < currentIdx) {
        node.classList.add('completed');
      } else if (stageIdx === currentIdx) {
        node.classList.add('active');
      }
    });

    lines.forEach((line, idx) => {
      line.classList.remove('completed');
      if (idx < currentIdx) {
        line.classList.add('completed');
      }
    });

    // Progression action triggers based on active stage
    if (actionContainer) {
      let buttonsHtml = '';
      if (currentStatus === 'AVAILABLE') {
        buttonsHtml = `
          <button class="btn btn-primary btn-sm" id="btn-action-match">
            <span>🤝 1. Match Org & Volunteer</span>
          </button>
        `;
      } else if (currentStatus === 'MATCHED') {
        buttonsHtml = `
          <button class="btn btn-primary btn-sm" id="btn-action-assign">
            <span>🚚 2. Assign Volunteer</span>
          </button>
        `;
      } else if (currentStatus === 'PICKUP_ASSIGNED' || currentStatus === 'PICKUP_PENDING') {
        buttonsHtml = `
          <button class="btn btn-secondary btn-sm" id="btn-action-enroute">
            <span>🚗 3. Mark En Route</span>
          </button>
          <button class="btn btn-primary btn-sm" id="btn-action-collected">
            <span>📦 4. Mark Collected</span>
          </button>
        `;
      } else if (currentStatus === 'EN_ROUTE') {
        buttonsHtml = `
          <button class="btn btn-primary btn-sm" id="btn-action-collected">
            <span>📦 4. Mark Collected</span>
          </button>
        `;
      } else if (currentStatus === 'COLLECTED') {
        buttonsHtml = `
          <button class="btn btn-primary btn-sm" id="btn-action-delivered">
            <span>✅ 5. Confirm Delivered</span>
          </button>
        `;
      } else if (currentStatus === 'DELIVERED') {
        buttonsHtml = `
          <span class="badge badge-primary">✨ Lifecycle Completed & Delivered</span>
        `;
      }

      actionContainer.innerHTML = buttonsHtml;

      // Attach button actions
      document.getElementById('btn-action-match')?.addEventListener('click', () => {
        sendChatAction(`Find a matching organization, create pickup task, and assign an available volunteer for donation ${don.id}.`);
      });

      document.getElementById('btn-action-assign')?.addEventListener('click', () => {
        sendChatAction(`Find an available volunteer for donation ${don.id} and assign them to the pickup task.`);
      });

      document.getElementById('btn-action-enroute')?.addEventListener('click', () => {
        sendChatAction(`Update the pickup task status for donation ${don.id} to EN_ROUTE.`);
      });

      document.getElementById('btn-action-collected')?.addEventListener('click', () => {
        sendChatAction(`Update the pickup task status for donation ${don.id} to COLLECTED.`);
      });

      document.getElementById('btn-action-delivered')?.addEventListener('click', () => {
        sendChatAction(`Update the pickup task status for donation ${don.id} to DELIVERED.`);
      });
    }
  }

  function selectDonation(donationId) {
    state.activeDonationId = donationId;
    renderDonations();
    showToast(`Viewing donation ${donationId}`, 'info');
  }

  // 3. Render Recipient Organizations View
  function renderOrganizations() {
    const container = document.getElementById('organizations-grid-container');
    const badge = document.getElementById('header-org-count');
    if (badge) badge.textContent = `${state.organizations.length} Verified Partners`;

    if (!container) return;

    if (state.organizations.length === 0) {
      container.innerHTML = `<div class="text-muted text-center py-8">No recipient organizations registered.</div>`;
      return;
    }

    container.innerHTML = state.organizations
      .map(
        (o) => `
      <div class="entity-card glass">
        <div class="entity-top">
          <div class="entity-title">🏢 ${escapeHtml(o.name)}</div>
          <span class="entity-id">${escapeHtml(o.id)}</span>
        </div>
        <div class="entity-details">
          <div class="entity-row">
            <span class="e-lbl">Service Area:</span>
            <span class="e-val">${escapeHtml(o.service_area)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Capacity:</span>
            <span class="e-val">${escapeHtml(o.capacity || 'High')}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Accepted Foods:</span>
            <span class="e-val">${escapeHtml(o.accepted_food_types)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Location:</span>
            <span class="e-val">📍 ${escapeHtml(o.location)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Contact Phone:</span>
            <span class="e-val">📞 ${escapeHtml(maskPhone(o.phone))}</span>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm btn-match-org" data-id="${o.id}">
          <span>View Matched Pickups</span>
        </button>
      </div>
    `
      )
      .join('');

    container.querySelectorAll('.btn-match-org').forEach((btn) => {
      btn.addEventListener('click', () => {
        switchTab('pickups');
      });
    });
  }

  // 4. Render Volunteers View
  function renderVolunteers() {
    const container = document.getElementById('volunteers-grid-container');
    const badge = document.getElementById('header-vol-count');
    if (badge) badge.textContent = `${state.volunteers.length} Active Couriers`;

    if (!container) return;

    if (state.volunteers.length === 0) {
      container.innerHTML = `
        <div class="text-muted text-center py-8" style="grid-column: 1 / -1; display: flex; flex-direction: column; align-items: center; gap: 1rem;">
          <div style="font-size: 2rem;">🚴</div>
          <div>No volunteers registered yet. Add couriers to the dispatch pool.</div>
          <button class="btn btn-primary btn-sm" id="btn-empty-register-vol">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
            <span>Register Volunteer Courier</span>
          </button>
        </div>
      `;
      document.getElementById('btn-empty-register-vol')?.addEventListener('click', () => {
        const volModal = document.getElementById('modal-create-volunteer');
        if (volModal) volModal.classList.add('active');
      });
      return;
    }

    container.innerHTML = state.volunteers
      .map(
        (v) => `
      <div class="entity-card glass">
        <div class="entity-top">
          <div class="entity-title">🚴 ${escapeHtml(v.name)}</div>
          <span class="status-badge status-${v.current_status === 'available' ? 'AVAILABLE' : 'MATCHED'}">${escapeHtml(v.current_status)}</span>
        </div>
        <div class="entity-details">
          <div class="entity-row">
            <span class="e-lbl">Courier ID:</span>
            <span class="e-val entity-id">${escapeHtml(v.id)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Service Area:</span>
            <span class="e-val">${escapeHtml(v.service_area)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Transport Mode:</span>
            <span class="e-val">${escapeHtml(v.transport_mode || 'Bicycle / Motorbike')}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Location:</span>
            <span class="e-val">📍 ${escapeHtml(v.location)}</span>
          </div>
          <div class="entity-row">
            <span class="e-lbl">Contact Phone:</span>
            <span class="e-val">📞 ${escapeHtml(maskPhone(v.phone))}</span>
          </div>
        </div>
        <button class="btn btn-secondary btn-sm btn-view-vol-tasks" data-id="${v.id}">
          <span>View Assigned Pickups</span>
        </button>
      </div>
    `
      )
      .join('');

    container.querySelectorAll('.btn-view-vol-tasks').forEach((btn) => {
      btn.addEventListener('click', () => {
        switchTab('pickups');
      });
    });
  }

  // Route Canvas Visualizer
  function drawRouteCanvas(originName, destName, courierCoords = null, isGpsActive = false) {
    const canvas = document.getElementById('route-map-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const w = canvas.width;
    const h = canvas.height;

    // Background
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, w, h);

    // Subtle Grid
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += 40) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    const pX = 120, pY = 110;  // Pickup (Donor)
    const dX = w - 140, dY = 110; // Delivery (Charity)

    // Route Connecting Line
    ctx.beginPath();
    ctx.moveTo(pX, pY);
    ctx.bezierCurveTo(pX + 200, pY - 50, dX - 200, dY + 50, dX, dY);
    ctx.strokeStyle = isGpsActive ? '#10b981' : '#38bdf8';
    ctx.lineWidth = 4;
    ctx.setLineDash(isGpsActive ? [] : [6, 4]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Glow Effect
    ctx.strokeStyle = isGpsActive ? 'rgba(16, 185, 129, 0.25)' : 'rgba(56, 189, 248, 0.2)';
    ctx.lineWidth = 12;
    ctx.stroke();

    // Courier Position (midpoint or dynamic)
    const cX = courierCoords ? (pX + (dX - pX) * 0.55) : (pX + (dX - pX) * 0.5);
    const cY = courierCoords ? (pY + (dY - pY) * 0.55 - 15) : (pY - 12);

    // Draw Courier Marker
    ctx.fillStyle = isGpsActive ? '#10b981' : '#f59e0b';
    ctx.beginPath();
    ctx.arc(cX, cY, isGpsActive ? 14 : 10, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('🚴', cX, cY + 4);

    if (isGpsActive) {
      ctx.strokeStyle = 'rgba(16, 185, 129, 0.5)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(cX, cY, 20, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.fillStyle = '#e2e8f0';
    ctx.font = '11px sans-serif';
    ctx.fillText(isGpsActive ? 'Courier (Live GPS)' : 'Volunteer Courier', cX, cY + 28);

    // Origin Marker (Donor)
    ctx.fillStyle = '#3b82f6';
    ctx.beginPath();
    ctx.arc(pX, pY, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.fillText('📍', pX, pY + 4);
    ctx.fillStyle = '#94a3b8';
    ctx.fillText('Donor: ' + (originName || 'Pickup Location'), pX, pY + 26);

    // Destination Marker (Charity)
    ctx.fillStyle = '#10b981';
    ctx.beginPath();
    ctx.arc(dX, dY, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.fillText('🏢', dX, dY + 4);
    ctx.fillStyle = '#94a3b8';
    ctx.fillText('Charity: ' + (destName || 'Delivery Location'), dX, dY + 26);
  }

  // 5. Render Pickups Logistics Board
  function renderPickups() {
    const tableBody = document.getElementById('pickups-table-body');
    const badge = document.getElementById('header-pickups-count');
    if (badge) badge.textContent = `${state.pickups.length} Logistics Tasks`;

    if (!tableBody) return;

    if (state.pickups.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="9" class="text-center py-8 text-muted">No pickup tasks scheduled yet.</td></tr>`;
      drawRouteCanvas('Colombo 3', 'Colombo 7', null, false);
      return;
    }

    // Pick the most active task for route visualization
    const activeTask = state.pickups.find(p => p.status === 'EN_ROUTE' || p.status === 'ASSIGNED') || state.pickups[0];
    
    // Update Route Overlay Header stats
    const distEl = document.getElementById('stat-route-distance');
    const etaEl = document.getElementById('stat-route-eta');
    const modeEl = document.getElementById('stat-transport-mode');
    const reimbEl = document.getElementById('stat-route-reimb');
    const provEl = document.getElementById('stat-routing-provider');

    if (activeTask) {
      const mode = 'Motorbike';
      const approxDist = '3.2 km';
      const approxCost = '160 LKR';
      const approxEta = '8 min';

      if (distEl) distEl.textContent = approxDist;
      if (etaEl) etaEl.textContent = approxEta;
      if (modeEl) modeEl.textContent = mode;
      if (reimbEl) reimbEl.textContent = approxCost;
      if (provEl) provEl.textContent = 'Google Routes / Haversine';

      const isGpsOn = state.activeGpsWatchId !== null && state.activeGpsPickupId === activeTask.id;
      drawRouteCanvas(activeTask.pickup_location, activeTask.delivery_location, state.lastGpsCoords, isGpsOn);
    }

    tableBody.innerHTML = state.pickups
      .map((p) => {
        const isGpsActive = state.activeGpsWatchId !== null && state.activeGpsPickupId === p.id;
        const mode = 'Motorbike';
        const estCost = '160 LKR';
        const estDist = '3.2 km (8m)';

        return `
        <tr>
          <td><code class="mini-don-id">${escapeHtml(p.id)}</code></td>
          <td><a href="#" class="link-don" data-id="${p.donation_id}">${escapeHtml(p.donation_id)}</a></td>
          <td><strong>${escapeHtml(p.organization_name || p.organization_id || 'Matched Org')}</strong></td>
          <td>${p.volunteer_name ? `🚴 ${escapeHtml(p.volunteer_name)} (${mode})` : '<span class="text-muted">Unassigned</span>'}</td>
          <td>📍 ${escapeHtml(p.pickup_location)} ➔ 🏢 ${escapeHtml(p.delivery_location)}</td>
          <td><span class="badge badge-emerald">${estDist} • ${estCost}</span></td>
          <td>
            <span class="gps-status-badge ${isGpsActive ? 'active' : 'inactive'}">
              <span class="gps-pulse"></span> ${isGpsActive ? 'Live GPS Active' : 'Off'}
            </span>
          </td>
          <td><span class="status-badge status-${p.status}">${escapeHtml(p.status)}</span></td>
          <td>
            <div class="table-actions-cluster">
              ${p.status === 'ASSIGNED' || p.status === 'EN_ROUTE' ? `
                <button class="btn btn-primary btn-xs btn-toggle-gps-row" data-id="${p.id}">
                  ${isGpsActive ? '⏹ Stop GPS' : '🛰️ Start GPS'}
                </button>
              ` : ''}
              <button class="btn btn-secondary btn-xs btn-advance-task" data-id="${p.id}" data-don="${p.donation_id}" data-status="${p.status}">
                ${p.status === 'ASSIGNED' ? 'Start Pickup' : p.status === 'EN_ROUTE' ? 'Mark Collected' : p.status === 'COLLECTED' ? 'Mark Delivered' : 'View Details'}
              </button>
            </div>
          </td>
        </tr>
      `;
      })
      .join('');

    tableBody.querySelectorAll('.link-don').forEach((link) => {
      link.addEventListener('click', (e) => {
        e.preventDefault();
        const donId = link.getAttribute('data-id');
        selectDonation(donId);
        switchTab('donations');
      });
    });

    tableBody.querySelectorAll('.btn-advance-task').forEach((btn) => {
      btn.addEventListener('click', () => {
        const donId = btn.getAttribute('data-don');
        const status = btn.getAttribute('data-status');
        let nextPrompt = `Check and progress status for donation ${donId}.`;
        if (status === 'ASSIGNED') {
          nextPrompt = `Update the pickup task status for donation ${donId} to EN_ROUTE.`;
        } else if (status === 'EN_ROUTE') {
          nextPrompt = `Update the pickup task status for donation ${donId} to COLLECTED.`;
        } else if (status === 'COLLECTED') {
          nextPrompt = `Update the pickup task status for donation ${donId} to DELIVERED.`;
        }
        sendChatAction(nextPrompt);
      });
    });

    tableBody.querySelectorAll('.btn-toggle-gps-row').forEach((btn) => {
      btn.addEventListener('click', () => {
        const pickupId = btn.getAttribute('data-id');
        toggleLiveGpsTracking(pickupId);
      });
    });
  }

  // Live GPS Geolocation Handlers
  function toggleLiveGpsTracking(pickupId) {
    if (state.activeGpsWatchId !== null) {
      stopLiveGpsTracking();
      showToast('Live GPS tracking stopped.', 'info');
    } else {
      startLiveGpsTracking(pickupId);
    }
  }

  function startLiveGpsTracking(pickupId) {
    if (!navigator.geolocation) {
      showToast('Browser geolocation is not supported on this device.', 'error');
      return;
    }

    showToast('Requesting GPS location permission...', 'info');

    state.activeGpsPickupId = pickupId;
    state.activeGpsWatchId = navigator.geolocation.watchPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        const acc = pos.coords.accuracy;
        state.lastGpsCoords = { latitude: lat, longitude: lng };

        try {
          await API.updatePickupLocation(pickupId, lat, lng, acc);
          const badge = document.getElementById('global-gps-badge');
          if (badge) {
            badge.className = 'gps-status-badge active';
            badge.innerHTML = `<span class="gps-pulse"></span> GPS Live: ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
          }
          renderPickups();
        } catch (e) {
          console.error('Failed to post GPS coordinate:', e);
        }
      },
      (err) => {
        console.warn('Geolocation watch error:', err.message);
        showToast('GPS access denied or unavailable. Fallback to estimated route coordinates.', 'info');
        stopLiveGpsTracking();
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 5000 }
    );

    const btn = document.getElementById('btn-toggle-live-gps');
    if (btn) btn.innerHTML = '<span>⏹ Stop Live GPS</span>';
    showToast(`Live GPS tracking activated for pickup ${pickupId}`, 'success');
  }

  function stopLiveGpsTracking() {
    if (state.activeGpsWatchId !== null) {
      navigator.geolocation.clearWatch(state.activeGpsWatchId);
      state.activeGpsWatchId = null;
      state.activeGpsPickupId = null;
    }

    const badge = document.getElementById('global-gps-badge');
    if (badge) {
      badge.className = 'gps-status-badge inactive';
      badge.innerHTML = `<span class="gps-pulse"></span> GPS Tracking Inactive`;
    }

    const btn = document.getElementById('btn-toggle-live-gps');
    if (btn) btn.innerHTML = '<span>🛰️ Start Live GPS</span>';
    renderPickups();
  }

  // 6. Render Reimbursements Ledger View (Phase 7)
  function renderReimbursements() {
    const tableBody = document.getElementById('reimbursements-table-body');
    const totalBadge = document.getElementById('header-reimb-total');
    const pendingBadge = document.getElementById('header-reimb-pending');
    const navBadge = document.getElementById('badge-reimbursements-count');

    const reimbs = state.reimbursements || [];
    if (navBadge) navBadge.textContent = reimbs.length;

    const totalPool = reimbs.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);
    const pendingCount = reimbs.filter(r => r.status === 'PENDING').length;

    if (totalBadge) totalBadge.textContent = `Pool: ${totalPool.toLocaleString()} LKR`;
    if (pendingBadge) pendingBadge.textContent = `${pendingCount} Pending Approval`;

    if (!tableBody) return;

    if (reimbs.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="10" class="text-center py-8 text-muted">No volunteer reimbursement records found. Reimbursements are automatically registered upon pickup delivery.</td></tr>`;
      return;
    }

    tableBody.innerHTML = reimbs
      .map(
        (r) => `
      <tr>
        <td><code class="mini-don-id">${escapeHtml(r.id)}</code></td>
        <td><strong>🚴 ${escapeHtml(r.volunteer_name || r.volunteer_id)}</strong></td>
        <td><code class="mini-don-id">${escapeHtml(r.pickup_task_id)}</code></td>
        <td>${parseFloat(r.distance_km).toFixed(1)} km</td>
        <td>${parseFloat(r.rate_per_km).toFixed(0)} LKR/km</td>
        <td>${escapeHtml(r.transport_mode)}</td>
        <td><strong class="text-emerald">${parseFloat(r.amount).toFixed(2)} ${escapeHtml(r.currency || 'LKR')}</strong></td>
        <td>
          <span class="status-badge status-${r.status}">${escapeHtml(r.status)}</span>
        </td>
        <td>${formatDate(r.created_at)}</td>
        <td>
          <div class="table-actions-cluster">
            ${r.status === 'PENDING' ? `
              <button class="btn btn-primary btn-xs btn-approve-reimb" data-id="${r.id}">
                ✓ Approve
              </button>
              <button class="btn btn-secondary btn-xs btn-pay-reimb" data-id="${r.id}">
                Mark Paid
              </button>
            ` : r.status === 'APPROVED' ? `
              <button class="btn btn-secondary btn-xs btn-pay-reimb" data-id="${r.id}">
                Mark Paid
              </button>
            ` : `
              <span class="text-muted text-xs">Record Finalized</span>
            `}
          </div>
        </td>
      </tr>
    `
      )
      .join('');

    tableBody.querySelectorAll('.btn-approve-reimb').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        try {
          await API.updateReimbursementStatus(id, 'APPROVED');
          showToast(`Reimbursement ${id} approved`, 'success');
          await loadAllData();
        } catch (e) {
          showToast(`Failed to approve: ${e.message}`, 'error');
        }
      });
    });

    tableBody.querySelectorAll('.btn-pay-reimb').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        try {
          await API.updateReimbursementStatus(id, 'PAID');
          showToast(`Reimbursement ${id} marked as PAID`, 'success');
          await loadAllData();
        } catch (e) {
          showToast(`Failed to mark paid: ${e.message}`, 'error');
        }
      });
    });
  }

  // 7. Render Session Memory Inspector
  function renderSessionInspector() {
    const kvContainer = document.getElementById('session-kv-container');
    const rawPre = document.getElementById('session-raw-json');
    const workflowBadge = document.getElementById('chat-workflow-badge');

    // Update active memory in chat sidebar
    const memDonId = document.getElementById('mem-active-don-id');
    const memDonorId = document.getElementById('mem-active-donor-id');
    const memFood = document.getElementById('mem-active-food');
    const memLoc = document.getElementById('mem-active-loc');
    const memDeadline = document.getElementById('mem-active-deadline');
    const memOrg = document.getElementById('mem-active-org');
    const memVol = document.getElementById('mem-active-vol');
    const memTask = document.getElementById('mem-active-task');

    const ctx = state.sessionContext || {};

    if (memDonId) memDonId.textContent = ctx.current_donation_id || 'None';
    if (memDonorId) memDonorId.textContent = ctx.current_donor_id || 'None';
    if (memFood) memFood.textContent = ctx.current_food_type ? `${ctx.current_quantity || ''} ${ctx.current_unit || ''} ${ctx.current_food_type}` : 'None';
    if (memLoc) memLoc.textContent = ctx.current_location || 'None';
    if (memDeadline) memDeadline.textContent = ctx.current_pickup_deadline || 'None';
    if (memOrg) memOrg.textContent = ctx.current_organization_id || 'None';
    if (memVol) memVol.textContent = ctx.current_volunteer_id || 'None';
    if (memTask) memTask.textContent = ctx.current_task_id || 'None';

    const step = ctx.workflow_step || 'IDLE';
    if (workflowBadge) workflowBadge.textContent = step;

    // Render KV List
    if (kvContainer) {
      const keys = Object.keys(ctx);
      if (keys.length === 0) {
        kvContainer.innerHTML = `<div class="text-muted text-center py-4">Active session created. No conversation context has been stored yet. Start a conversation to populate session memory.</div>`;
      } else {
        kvContainer.innerHTML = keys
          .map(
            (k) => `
          <div class="kv-item">
            <span class="kv-key">${escapeHtml(k)}</span>
            <span class="kv-val">${escapeHtml(String(ctx[k]))}</span>
          </div>
        `
          )
          .join('');
      }
    }

    if (rawPre) {
      rawPre.textContent = JSON.stringify(ctx, null, 2);
    }
  }

  // ==========================================
  // CHAT CONTROLLER
  // ==========================================
  async function submitChatPrompt(promptText) {
    if (!promptText || !promptText.trim() || state.isChatThinking) return;

    const cleanPrompt = promptText.trim();
    const chatLog = document.getElementById('chat-messages-log');
    const inputArea = document.getElementById('chat-user-prompt');

    if (inputArea) inputArea.value = '';

    // Append User Message Bubble
    appendMessageBubble('user', cleanPrompt);

    // Append Thinking Indicator
    state.isChatThinking = true;
    const thinkingRow = document.createElement('div');
    thinkingRow.className = 'chat-bubble-row assistant thinking-row';
    thinkingRow.innerHTML = `
      <div class="bubble-avatar">🤖</div>
      <div class="bubble-content">
        <div class="bubble-header"><span class="bubble-sender">FoodRescue AI Assistant</span></div>
        <div class="bubble-text"><div class="loading-spinner" style="margin: 0; width: 18px; height: 18px;"></div> Coordinating via Agent Kernel & Gemini...</div>
      </div>
    `;
    chatLog.appendChild(thinkingRow);
    chatLog.scrollTop = chatLog.scrollHeight;

    try {
      const data = await API.sendChatPrompt(cleanPrompt, state.sessionId);
      thinkingRow.remove();

      const assistantReply = data.result || data.response || 'Action completed.';
      appendMessageBubble('assistant', assistantReply);

      // Refresh all live backend data
      await loadAllData();
    } catch (err) {
      thinkingRow.remove();
      appendMessageBubble('assistant', `⚠️ **Error coordinating request**: ${err.message}`);
      showToast(err.message, 'error');
    } finally {
      state.isChatThinking = false;
    }
  }

  function appendMessageBubble(sender, text) {
    const chatLog = document.getElementById('chat-messages-log');
    if (!chatLog) return;

    const row = document.createElement('div');
    row.className = `chat-bubble-row ${sender}`;

    const avatar = sender === 'assistant' ? '🤖' : '👤';
    const senderName = sender === 'assistant' ? 'FoodRescue AI Assistant' : 'You (Donor / Dispatcher)';
    const formattedContent = formatMarkdown(text);

    row.innerHTML = `
      <div class="bubble-avatar">${avatar}</div>
      <div class="bubble-content">
        <div class="bubble-header">
          <span class="bubble-sender">${senderName}</span>
          <span class="bubble-time">${formatTime(new Date().toISOString())}</span>
        </div>
        <div class="bubble-text">${formattedContent}</div>
      </div>
    `;

    chatLog.appendChild(row);
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  function sendChatAction(prompt) {
    switchTab('chat');
    submitChatPrompt(prompt);
  }

  // ==========================================
  // MULTI-TURN DEMO WALKTHROUGH AUTOMATION
  // ==========================================
  async function runMultiTurnDemoFlow() {
    showToast('Starting 3-Turn Multi-Turn Demo Walkthrough...', 'info');
    switchTab('chat');

    // Reset session for a clean demonstration with a dedicated demo prefix
    state.sessionId = 'demo-session-' + Math.random().toString(36).substring(2, 9);
    updateSessionDisplay();

    appendMessageBubble('assistant', '🚀 **Starting 3-Turn Multi-Turn Session Demonstration**\nDemonstrating seamless context preservation across three conversational turns.');
    await delay(1000);

    // Turn 1: Partial Details
    const turn1 = 'I am donor d1. I have 40 vegetarian lunch boxes in Colombo 3.';
    await submitChatPrompt(turn1);

    await delay(2500);

    // Turn 2: Incremental Detail Update (No reprompting)
    const turn2 = 'They need to be collected before 7 PM.';
    await submitChatPrompt(turn2);

    await delay(2500);

    // Turn 3: Complete Matching & Assignment
    const turn3 = 'Find a matching organization, schedule pickup, and assign an available volunteer.';
    await submitChatPrompt(turn3);

    showToast('Multi-Turn Coordination Flow Successfully Completed!', 'success');
  }

  function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // ==========================================
  // DATA LOADING & REFRESH
  // ==========================================
  async function loadAllData() {
    try {
      const [statsRes, donRes, orgRes, volRes, pickRes, reimbRes, notifRes, sessRes] = await Promise.all([
        API.getStats().catch(() => null),
        API.getDonations().catch(() => ({ donations: [] })),
        API.getOrganizations().catch(() => ({ organizations: [] })),
        API.getVolunteers().catch(() => ({ volunteers: [] })),
        API.getPickups().catch(() => ({ pickup_tasks: [] })),
        API.getReimbursements().catch(() => ({ reimbursements: [] })),
        API.getNotifications().catch(() => ({ notifications: [] })),
        API.getSessionState(state.sessionId).catch(() => ({ context: {} })),
      ]);

      if (statsRes?.stats) state.stats = statsRes.stats;
      if (donRes?.donations) state.donations = donRes.donations;
      if (orgRes?.organizations) state.organizations = orgRes.organizations;
      if (volRes?.volunteers) state.volunteers = volRes.volunteers;
      if (pickRes?.pickup_tasks) state.pickups = pickRes.pickup_tasks;
      if (reimbRes?.reimbursements) state.reimbursements = reimbRes.reimbursements;
      if (notifRes?.notifications) state.notifications = notifRes.notifications;
      if (sessRes?.context) state.sessionContext = sessRes.context;

      renderDashboard();
      renderDonations();
      renderOrganizations();
      renderVolunteers();
      renderPickups();
      renderReimbursements();
      renderSessionInspector();
    } catch (err) {
      console.error('Error refreshing live data:', err);
    }
  }

  // Tab Navigation Controller (8 Tabs)
  function switchTab(tabId) {
    state.activeTab = tabId;

    // Update Nav buttons
    document.querySelectorAll('.nav-item').forEach((item) => {
      item.classList.toggle('active', item.getAttribute('data-tab') === tabId);
    });

    // Update Tab Contents
    document.querySelectorAll('.tab-content').forEach((tab) => {
      tab.classList.toggle('active', tab.id === `tab-${tabId}`);
    });

    // Update Page Header Title
    const titleMap = {
      dashboard: 'Dashboard Overview',
      chat: 'AI Assistant Coordinator',
      donations: 'Donations & 7-Stage Lifecycle',
      organizations: 'Recipient Organizations & Food Banks',
      volunteers: 'Volunteer Couriers',
      pickups: 'Pickup & Delivery Logistics',
      reimbursements: 'Volunteer Reimbursement Ledger',
      session: 'Session Memory & Activity Audit',
    };
    const pageTitle = document.getElementById('page-title');
    if (pageTitle) pageTitle.textContent = titleMap[tabId] || 'FoodRescue AI';
  }

  function updateSessionDisplay() {
    const el = document.getElementById('header-session-id');
    if (el) el.textContent = state.sessionId;
  }

  // ==========================================
  // INITIALIZATION & EVENT LISTENERS
  // ==========================================
  function initEventListeners() {
    // Navigation Tabs
    document.querySelectorAll('.nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-tab');
        if (tab) switchTab(tab);
      });
    });

    // Global Live GPS Toggle Button
    document.getElementById('btn-toggle-live-gps')?.addEventListener('click', () => {
      const activeTask = state.pickups.find(p => p.status === 'EN_ROUTE' || p.status === 'ASSIGNED') || state.pickups[0];
      const targetId = activeTask ? activeTask.id : 'task-demo';
      toggleLiveGpsTracking(targetId);
    });

    // Header Actions
    document.getElementById('btn-refresh-all')?.addEventListener('click', async () => {
      await loadAllData();
      showToast('Live database records refreshed', 'info');
    });

    document.getElementById('btn-run-demo-flow')?.addEventListener('click', runMultiTurnDemoFlow);
    document.getElementById('btn-run-demo-chat')?.addEventListener('click', runMultiTurnDemoFlow);

    document.getElementById('btn-new-session')?.addEventListener('click', () => {
      state.sessionId = generateSessionId();
      updateSessionDisplay();
      loadAllData();
      showToast(`Started new session ${state.sessionId}`, 'info');
    });

    document.getElementById('btn-copy-session')?.addEventListener('click', () => {
      navigator.clipboard.writeText(state.sessionId);
      showToast('Session ID copied to clipboard', 'info');
    });

    // Chat Form Submit
    const chatForm = document.getElementById('chat-input-form');
    const chatInput = document.getElementById('chat-user-prompt');

    if (chatForm && chatInput) {
      chatForm.addEventListener('submit', (e) => {
        e.preventDefault();
        submitChatPrompt(chatInput.value);
      });

      chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          submitChatPrompt(chatInput.value);
        }
      });
    }

    // Chat Suggestion Chips
    document.querySelectorAll('.chat-suggestions .chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        const prompt = chip.getAttribute('data-prompt');
        if (prompt) submitChatPrompt(prompt);
      });
    });

    // Chat Quick Action Sidebar Buttons
    document.getElementById('btn-quick-create-d1')?.addEventListener('click', () => {
      submitChatPrompt('I am donor d1. I have 40 vegetarian lunch boxes in Colombo 3 ready from now until 7 PM.');
    });

    document.getElementById('btn-quick-update-time')?.addEventListener('click', () => {
      submitChatPrompt('They need to be collected before 7 PM.');
    });

    document.getElementById('btn-quick-match-assign')?.addEventListener('click', () => {
      submitChatPrompt('Find a matching organization, create pickup task, and assign an available volunteer.');
    });

    document.getElementById('btn-quick-en-route')?.addEventListener('click', () => {
      submitChatPrompt('Update the active pickup task status to EN_ROUTE.');
    });

    document.getElementById('btn-quick-delivered')?.addEventListener('click', () => {
      submitChatPrompt('Update the active pickup task status to DELIVERED.');
    });

    document.getElementById('btn-clear-chat')?.addEventListener('click', () => {
      const chatLog = document.getElementById('chat-messages-log');
      if (chatLog) {
        chatLog.innerHTML = `
          <div class="chat-bubble-row assistant">
            <div class="bubble-avatar">🤖</div>
            <div class="bubble-content">
              <div class="bubble-header"><span class="bubble-sender">FoodRescue AI Assistant</span></div>
              <div class="bubble-text">Chat cleared. Ready for your next food rescue command!</div>
            </div>
          </div>
        `;
      }
    });

    // Status Filter Pills
    document.querySelectorAll('#status-filter-group .pill').forEach((pill) => {
      pill.addEventListener('click', async () => {
        document.querySelectorAll('#status-filter-group .pill').forEach((p) => p.classList.remove('active'));
        pill.classList.add('active');

        const filter = pill.getAttribute('data-filter');
        const res = await API.getDonations(filter);
        if (res?.donations) {
          state.donations = res.donations;
          renderDonations();
        }
      });
    });

    // Search Input
    document.getElementById('donation-search-input')?.addEventListener('input', (e) => {
      const q = e.target.value.toLowerCase().trim();
      const rows = document.querySelectorAll('#donations-table-body tr');
      rows.forEach((row) => {
        const text = row.textContent.toLowerCase();
        row.style.display = text.includes(q) ? '' : 'none';
      });
    });

    // View All Donations from Dashboard
    document.getElementById('btn-view-all-donations')?.addEventListener('click', () => {
      switchTab('donations');
    });

    // Modal Create Donation
    const modal = document.getElementById('modal-create-donation');
    const openModalBtn = document.getElementById('btn-open-donation-modal');
    const openModalTabBtn = document.getElementById('btn-new-donation-tab');
    const closeModalBtn = document.getElementById('btn-close-modal');
    const cancelModalBtn = document.getElementById('btn-cancel-modal');
    const formDonation = document.getElementById('form-create-donation');

    function openModal() {
      if (modal) modal.classList.add('active');
    }

    function closeModal() {
      if (modal) modal.classList.remove('active');
    }

    if (openModalBtn) openModalBtn.addEventListener('click', openModal);
    if (openModalTabBtn) openModalTabBtn.addEventListener('click', openModal);
    if (closeModalBtn) closeModalBtn.addEventListener('click', closeModal);
    if (cancelModalBtn) cancelModalBtn.addEventListener('click', closeModal);

    if (formDonation) {
      formDonation.addEventListener('submit', async (e) => {
        e.preventDefault();
        const donorId = document.getElementById('input-donor-id').value;
        const foodType = document.getElementById('input-food-type').value;
        const quantity = document.getElementById('input-quantity').value;
        const unit = document.getElementById('input-unit').value;
        const dietary = document.getElementById('input-dietary').value;
        const location = document.getElementById('input-location').value;
        const availFrom = document.getElementById('input-available-from').value;
        const deadline = document.getElementById('input-deadline').value;

        closeModal();

        // Construct natural language prompt to Agent Kernel
        const prompt = `I am donor ${donorId}. I have ${quantity} ${unit} of ${foodType} (${dietary}) in ${location}, available from ${availFrom} until ${deadline}. Please register this donation and find a match.`;

        switchTab('chat');
        await submitChatPrompt(prompt);
      });
    }

    // Modal Create Volunteer
    const volModal = document.getElementById('modal-create-volunteer');
    const openVolModalBtn = document.getElementById('btn-open-volunteer-modal');
    const closeVolModalBtn = document.getElementById('btn-close-volunteer-modal');
    const cancelVolModalBtn = document.getElementById('btn-cancel-volunteer-modal');
    const formVolunteer = document.getElementById('form-create-volunteer');

    function openVolModal() {
      if (volModal) volModal.classList.add('active');
    }

    function closeVolModal() {
      if (volModal) volModal.classList.remove('active');
    }

    if (openVolModalBtn) openVolModalBtn.addEventListener('click', openVolModal);
    if (closeVolModalBtn) closeVolModalBtn.addEventListener('click', closeVolModal);
    if (cancelVolModalBtn) cancelVolModalBtn.addEventListener('click', closeVolModal);

    if (formVolunteer) {
      formVolunteer.addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('input-vol-name').value;
        const phone = document.getElementById('input-vol-phone').value;
        const serviceArea = document.getElementById('input-vol-area').value;
        const transportMode = document.getElementById('input-vol-transport').value;
        const availability = document.getElementById('input-vol-availability').value;
        const location = document.getElementById('input-vol-location').value;

        try {
          const res = await API.createVolunteer({
            name,
            phone,
            service_area: serviceArea,
            transport_mode: transportMode,
            availability,
            location,
          });

          closeVolModal();
          showToast(`Volunteer courier "${name}" registered successfully!`, 'success');
          await loadAllData();
          switchTab('volunteers');
        } catch (err) {
          showToast(`Failed to register volunteer: ${err.message}`, 'error');
        }
      });
    }

    // Session Clear State Button
    document.getElementById('btn-clear-session-state')?.addEventListener('click', async () => {
      await submitChatPrompt('Clear active session context and reset working memory.');
      showToast('Session context cleared', 'info');
    });

    document.getElementById('btn-refresh-session')?.addEventListener('click', async () => {
      const sessRes = await API.getSessionState(state.sessionId);
      if (sessRes?.context) state.sessionContext = sessRes.context;
      renderSessionInspector();
      showToast('Session memory inspected', 'info');
    });
  }

  // Initialize App on DOM Ready
  document.addEventListener('DOMContentLoaded', async () => {
    updateSessionDisplay();
    initEventListeners();

    // Check server connection
    const isOnline = await API.checkHealth();
    const dot = document.getElementById('server-status-dot');
    const title = document.getElementById('server-status-title');

    if (dot && title) {
      dot.className = isOnline ? 'status-indicator online' : 'status-indicator offline';
      title.textContent = isOnline ? 'Agent Kernel Live' : 'Backend Offline';
    }

    // Load initial data
    await loadAllData();

    // Auto-refresh polling every 6 seconds
    state.autoRefreshInterval = setInterval(loadAllData, 6000);
  });
})();
