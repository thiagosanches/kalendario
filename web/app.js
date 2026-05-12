// Kalendario - Event Scheduler

let currentDate = new Date();
let appointments = [];
let viewMode = '7days'; // 'month' or '7days'
let startDate = new Date(); // For 7-day view

// Frequency labels in Portuguese
const FREQ_LABELS = { daily: 'Diário', weekly: 'Semanal', biweekly: 'Quinzenal', monthly: 'Mensal', yearly: 'Anual' };

// Format a Date object as YYYY-MM-DD
function formatDateStr(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

// Resolve display title: prefer doctor field (legacy name for event title),
// fall back to description so old entries without a doctor field still show something.
function getTitle(apt) {
    return apt.doctor || apt.description || '';
}

// Add n months to a date, clamping to end of month (mirrors Python _add_months)
function addMonthsJS(date, n) {
    const d = new Date(date);
    const targetMonth = d.getMonth() + n;
    const year = d.getFullYear() + Math.floor(targetMonth / 12);
    const month = ((targetMonth % 12) + 12) % 12;
    const day = Math.min(d.getDate(), new Date(year, month + 1, 0).getDate());
    return new Date(year, month, day);
}

// Expand recurring appointments into concrete occurrences within [fromDate, toDate].
// Non-recurring entries are returned as-is. Recurring ones get _recurring: true.
function expandAppointments(apts, fromDate, toDate) {
    const result = [];
    for (const apt of apts) {
        if (!apt.recurrence) {
            const aptDate = new Date(apt.date + 'T00:00:00');
            if (aptDate >= fromDate && aptDate <= toDate) result.push(apt);
            continue;
        }
        const recEnd = apt.recurrence_end
            ? new Date(apt.recurrence_end + 'T23:59:00')
            : toDate;
        const effectiveEnd = recEnd < toDate ? recEnd : toDate;
        let current = new Date(apt.date + 'T00:00:00');
        while (current <= effectiveEnd) {
            if (current >= fromDate) {
                result.push({ ...apt, date: formatDateStr(current), _recurring: true });
            }
            if (apt.recurrence === 'daily') {
                current.setDate(current.getDate() + 1);
            } else if (apt.recurrence === 'weekly') {
                current.setDate(current.getDate() + 7);
            } else if (apt.recurrence === 'biweekly') {
                current.setDate(current.getDate() + 14);
            } else if (apt.recurrence === 'monthly') {
                current = addMonthsJS(current, 1);
            } else if (apt.recurrence === 'yearly') {
                current = addMonthsJS(current, 12);
            } else {
                break;
            }
        }
    }
    return result;
}

// Initialize the application
async function init() {
    updateCurrentDate();
    await loadAppointments();
    renderView();
    renderAppointmentsList();
    renderPastEvents();
    updateRefreshTime();
    
    // Event listeners
    document.getElementById('prevPeriod').addEventListener('click', () => {
        if (viewMode === 'month') {
            currentDate.setMonth(currentDate.getMonth() - 1);
        } else {
            startDate.setDate(startDate.getDate() - 7);
        }
        renderView();
        renderAppointmentsList();
    });
    
    document.getElementById('nextPeriod').addEventListener('click', () => {
        if (viewMode === 'month') {
            currentDate.setMonth(currentDate.getMonth() + 1);
        } else {
            startDate.setDate(startDate.getDate() + 7);
        }
        renderView();
        renderAppointmentsList();
    });
    
    document.getElementById('monthViewBtn').addEventListener('click', () => {
        viewMode = 'month';
        document.getElementById('monthViewBtn').classList.add('active');
        document.getElementById('days15ViewBtn').classList.remove('active');
        renderView();
        renderAppointmentsList();
    });
    
    document.getElementById('days15ViewBtn').addEventListener('click', () => {
        viewMode = '7days';
        startDate = new Date(); // Reset to today
        document.getElementById('days15ViewBtn').classList.add('active');
        document.getElementById('monthViewBtn').classList.remove('active');
        renderView();
        renderAppointmentsList();
    });
    
    // Manual refresh button
    document.getElementById('refreshBtn').addEventListener('click', async () => {
        console.log('🔄 Manual refresh triggered');
        const btn = document.getElementById('refreshBtn');
        btn.classList.add('refreshing');
        await refreshData();
        btn.classList.remove('refreshing');
    });
    
    // Dark mode toggle
    document.getElementById('darkModeToggle').addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
        const isDark = document.body.classList.contains('dark-mode');
        localStorage.setItem('darkMode', isDark ? 'enabled' : 'disabled');
        document.getElementById('darkModeToggle').textContent = isDark ? '☀️' : '🌙';
    });
    
    // Load saved dark mode preference
    const darkModePreference = localStorage.getItem('darkMode');
    if (darkModePreference === 'enabled') {
        document.body.classList.add('dark-mode');
        document.getElementById('darkModeToggle').textContent = '☀️';
    }
    
    // Auto-refresh every 2 minutes
    setInterval(async () => {
        console.log('🔄 Auto refresh triggered');
        await refreshData();
    }, 120000);
}

// Refresh all data
async function refreshData() {
    await loadAppointments();
    renderView();
    renderAppointmentsList();
    renderPastEvents();
    updateRefreshTime();
}

// Update the last refresh time display
function updateRefreshTime() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    document.getElementById('lastRefresh').textContent = `Última atualização: ${timeStr}`;
}

// Render view based on mode
function renderView() {
    const mainContent = document.querySelector('.main-content');
    if (viewMode === 'month') {
        mainContent.classList.remove('days7-mode');
        renderMonthCalendar();
    } else {
        mainContent.classList.add('days7-mode');
        render7DaysView();
    }
}

// Update current date display
function updateCurrentDate() {
    const options = { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' };
    document.getElementById('currentDate').textContent = new Date().toLocaleDateString('pt-BR', options);
}

// Load appointments from JSON file
async function loadAppointments() {
    try {
        // Try multiple paths with cache-busting timestamp
        const timestamp = new Date().getTime();
        const paths = [
            `/appointments.json?t=${timestamp}`,  // Nginx serves from /data/appointments.json
            `../data/appointments.json?t=${timestamp}`,  // Direct access when using file server
            `/data/appointments.json?t=${timestamp}`  // Alternative path
        ];
        
        let response = null;
        let successPath = null;
        
        for (const path of paths) {
            try {
                response = await fetch(path, {
                    cache: 'no-store', // Prevent caching
                    headers: {
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache'
                    }
                });
                if (response.ok) {
                    successPath = path;
                    console.log('✅ Successfully loaded from:', path);
                    break;
                }
            } catch (e) {
                console.log('❌ Failed to load from:', path, e.message);
            }
        }
        
        if (!response || !response.ok) {
            throw new Error('Could not load appointments from any path');
        }
        
        const data = await response.json();
        appointments = data.appointments || [];
        console.log('📅 Loaded appointments:', appointments.length);
        console.log('🔄 Last update:', new Date().toLocaleTimeString('pt-BR'));
        
        if (appointments.length > 0) {
            console.log('📋 Sample appointment:', appointments[0]);
        }
    } catch (error) {
        console.error('❌ Error loading appointments:', error);
        appointments = [];
    }
}

// Render calendar
function renderMonthCalendar() {
    const calendar = document.getElementById('calendar');
    const periodTitle = document.getElementById('periodTitle');
    
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    
    // Set month and year header
    const monthNames = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
    periodTitle.textContent = `${monthNames[month]} ${year}`;
    
    // Clear calendar
    calendar.innerHTML = '';
    calendar.className = 'calendar-grid month-view';
    
    // Add day headers
    const days = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
    days.forEach(day => {
        const dayHeader = document.createElement('div');
        dayHeader.className = 'calendar-day-header';
        dayHeader.textContent = day;
        calendar.appendChild(dayHeader);
    });
    
    // Get first day of month and number of days
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    
    // Add empty cells for days before month starts
    for (let i = 0; i < firstDay; i++) {
        const emptyCell = document.createElement('div');
        emptyCell.className = 'calendar-day empty';
        calendar.appendChild(emptyCell);
    }
    
    // Expand recurring appointments for this month
    const monthFrom = new Date(year, month, 1);
    const monthTo = new Date(year, month + 1, 0, 23, 59, 59);
    const expandedMonthApts = expandAppointments(appointments, monthFrom, monthTo);

    // Add days of the month
    const today = new Date();
    for (let day = 1; day <= daysInMonth; day++) {
        const dayCell = document.createElement('div');
        dayCell.className = 'calendar-day';
        
        const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
        
        // Check if today
        if (year === today.getFullYear() && month === today.getMonth() && day === today.getDate()) {
            dayCell.classList.add('today');
        }
        
        // Check for appointments on this day (including expanded recurring occurrences)
        const dayAppointments = expandedMonthApts.filter(apt => apt.date === dateStr);
        const hasRecurring = dayAppointments.some(apt => apt._recurring);
        
        dayCell.innerHTML = `
            <div class="day-number">${day}</div>
            ${dayAppointments.length > 0 ? `<div class="appointment-indicator${hasRecurring ? ' recurring-indicator' : ''}">${dayAppointments.length}</div>` : ''}
        `;
        
        if (dayAppointments.length > 0) {
            dayCell.classList.add('has-appointment');
            if (hasRecurring) dayCell.classList.add('has-recurring');
            dayCell.title = dayAppointments.map(apt => `${apt.time} - ${getTitle(apt)}${apt._recurring ? ' 🔁' : ''}`).join('\n');
        }
        
        calendar.appendChild(dayCell);
    }
}

// Render 7-day view with appointment details
function render7DaysView() {
    const calendar = document.getElementById('calendar');
    const periodTitle = document.getElementById('periodTitle');
    
    const endDate = new Date(startDate);
    endDate.setDate(endDate.getDate() + 6);
    
    const monthNames = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun',
                        'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
    
    periodTitle.textContent = `${startDate.getDate()} ${monthNames[startDate.getMonth()]} - ${endDate.getDate()} ${monthNames[endDate.getMonth()]}, ${startDate.getFullYear()}`;
    
    // Clear calendar
    calendar.innerHTML = '';
    calendar.className = 'calendar-grid days7-view';
    
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    // Expand recurring appointments for the 7-day window
    const windowStart = new Date(startDate);
    windowStart.setHours(0, 0, 0, 0);
    const windowEnd = new Date(startDate);
    windowEnd.setDate(windowEnd.getDate() + 6);
    windowEnd.setHours(23, 59, 59);
    const expanded7DayApts = expandAppointments(appointments, windowStart, windowEnd);

    // Create 7 day cards
    for (let i = 0; i < 7; i++) {
        const currentDay = new Date(startDate);
        currentDay.setDate(currentDay.getDate() + i);
        
        const dateStr = `${currentDay.getFullYear()}-${String(currentDay.getMonth() + 1).padStart(2, '0')}-${String(currentDay.getDate()).padStart(2, '0')}`;
        
        const dayCard = document.createElement('div');
        dayCard.className = 'day-card';
        
        // Check if today
        const isToday = currentDay.getTime() === today.getTime();
        if (isToday) {
            dayCard.classList.add('today');
        }
        
        // Get appointments for this day (including expanded recurring occurrences)
        const dayAppointments = expanded7DayApts.filter(apt => apt.date === dateStr);
        dayAppointments.sort((a, b) => a.time.localeCompare(b.time));
        
        const dayNames = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
        const dayName = dayNames[currentDay.getDay()];
        
        let appointmentsHTML = '';
        if (dayAppointments.length > 0) {
            appointmentsHTML = dayAppointments.map(apt => {
                const isReminder = apt.type === 'reminder';
                const isRecurring = apt._recurring;
                const cssClass = isRecurring ? 'day-appointment recurring'
                    : (isReminder ? 'day-appointment reminder' : 'day-appointment');
                const icon = isRecurring ? '🔁' : (isReminder ? '⏰' : '📅');
                const recurBadge = isRecurring
                    ? `<div class="recurrence-badge">🔁 ${FREQ_LABELS[apt.recurrence] || apt.recurrence}</div>`
                    : '';

                return `
                <div class="${cssClass}">
                    <div class="day-apt-time">${icon} ${apt.time}</div>
                    <div class="day-apt-details">
                        ${recurBadge}
                        ${getTitle(apt) ? `<div class="day-apt-doctor">${getTitle(apt)}</div>` : ''}
                        ${apt.description && apt.description !== getTitle(apt) ? `<div class="day-apt-desc">${apt.description}</div>` : ''}
                        ${apt.location ? `<div class="day-apt-location">📍 ${apt.location}</div>` : ''}
                    </div>
                </div>
            `;
            }).join('');
        } else {
            appointmentsHTML = '<div class="no-appointments-day">Sem eventos ou lembretes</div>';
        }
        
        dayCard.innerHTML = `
            <div class="day-card-header">
                <div class="day-card-date">
                    <div class="day-card-day">${dayName}</div>
                    <div class="day-card-number">${currentDay.getDate()}</div>
                    <div class="day-card-month">${monthNames[currentDay.getMonth()]}</div>
                </div>
            </div>
            <div class="day-card-appointments">
                ${appointmentsHTML}
            </div>
        `;
        
        calendar.appendChild(dayCard);
    }
}

// Render appointments list
function renderAppointmentsList() {
    const list = document.getElementById('appointmentsList');
    const heading = document.querySelector('.appointments-section h2');

    // Determine the window based on current view
    let windowFrom, windowTo;
    const monthNames = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
    if (viewMode === 'month') {
        windowFrom = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1, 0, 0, 0);
        windowTo   = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 0, 23, 59, 59);
        heading.textContent = `Lembretes de ${monthNames[currentDate.getMonth()]} ${currentDate.getFullYear()}`;
    } else {
        windowFrom = new Date(startDate);
        windowFrom.setHours(0, 0, 0, 0);
        windowTo = new Date(startDate);
        windowTo.setDate(windowTo.getDate() + 6);
        windowTo.setHours(23, 59, 59);
        heading.textContent = 'Próximos Lembretes';
    }

    const expandedApts = expandAppointments(appointments, windowFrom, windowTo);

    // Sort appointments by date and time
    const sortedAppointments = expandedApts.sort((a, b) => {
        const dateA = new Date(`${a.date}T${a.time}`);
        const dateB = new Date(`${b.date}T${b.time}`);
        return dateA - dateB;
    });

    if (sortedAppointments.length === 0) {
        list.innerHTML = '<div class="no-appointments">Nenhum lembrete agendado</div>';
        return;
    }

    const futureAppointments = sortedAppointments;
    
    list.innerHTML = futureAppointments.map(apt => {
        const aptDate = new Date(`${apt.date}T${apt.time}`);
        const dateStr = aptDate.toLocaleDateString('pt-BR', { weekday: 'short', month: 'short', day: 'numeric' });
        const isReminder = apt.type === 'reminder';
        const isRecurring = apt._recurring;
        const cardClass = isRecurring ? 'appointment-card recurring-card'
            : (isReminder ? 'appointment-card reminder-card-style' : 'appointment-card');
        const icon = isRecurring ? '🔁' : (isReminder ? '⏰' : '📅');
        const recurBadge = isRecurring
            ? `<div class="recurrence-badge">🔁 ${FREQ_LABELS[apt.recurrence] || apt.recurrence}</div>`
            : '';
        
        return `
            <div class="${cardClass}">
                <div class="appointment-date">
                    <div class="date-large">${dateStr}</div>
                    <div class="time-large">${apt.time}</div>
                </div>
                <div class="appointment-details">
                    ${recurBadge}
                    ${getTitle(apt) ? `<div class="appointment-doctor">${getTitle(apt)}</div>` : ''}
                    ${apt.description && apt.description !== getTitle(apt) ? `<div class="appointment-description">${icon} ${apt.description}</div>` : `<div class="appointment-description">${icon}</div>`}
                    ${apt.location ? `<div class="appointment-location">📍 ${apt.location}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// Render today's reminders
function renderTodayReminders() {
    const list = document.getElementById('todayReminders');
    const today = new Date();
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0);

    // Window: today → end of next week (next Sunday + 7 days)
    const dayOfWeek = today.getDay(); // 0=Sun, 1=Mon, …, 6=Sat
    const daysToSunday = dayOfWeek === 0 ? 0 : 7 - dayOfWeek;
    const windowEnd = new Date(todayStart);
    windowEnd.setDate(todayStart.getDate() + daysToSunday + 7);
    windowEnd.setHours(23, 59, 59, 999);

    const expanded = expandAppointments(appointments, todayStart, windowEnd)
        .filter(apt => apt.date >= formatDateStr(todayStart))
        .sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time));

    if (expanded.length === 0) {
        list.innerHTML = '<div class="no-reminders">Nenhum evento esta semana</div>';
        return;
    }

    // Group by date
    const byDate = {};
    for (const apt of expanded) {
        if (!byDate[apt.date]) byDate[apt.date] = [];
        byDate[apt.date].push(apt);
    }

    const todayStr = formatDateStr(today);
    const WEEKDAYS_PT = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];

    list.innerHTML = Object.entries(byDate).map(([date, apts]) => {
        const d = new Date(date + 'T00:00:00');
        const label = date === todayStr
            ? 'Hoje'
            : `${WEEKDAYS_PT[d.getDay()]}, ${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;

        const cards = apts.map(apt => {
            const isReminder = apt.type === 'reminder';
            const isRecurring = apt._recurring;
            const icon = isRecurring ? '🔁' : (isReminder ? '⏰' : '📅');
            const cardClass = isRecurring ? 'reminder-card recurring'
                : (isReminder ? 'reminder-card reminder-type' : 'reminder-card');
            const recurBadge = isRecurring
                ? `<div class="recurrence-badge">🔁 ${FREQ_LABELS[apt.recurrence] || apt.recurrence}</div>`
                : '';
            return `
            <div class="${cardClass}">
                <div class="reminder-time">${icon} ${apt.time}</div>
                <div class="reminder-details">
                    ${recurBadge}
                    ${getTitle(apt) ? `<div class="reminder-doctor">${getTitle(apt)}</div>` : ''}
                    ${apt.description && apt.description !== getTitle(apt) ? `<div class="reminder-description">${apt.description}</div>` : ''}
                    ${apt.location ? `<div class="reminder-location">${apt.location}</div>` : ''}
                </div>
            </div>`;
        }).join('');

        return `<div class="reminders-day-group">
            <div class="reminders-day-label">${label}</div>
            ${cards}
        </div>`;
    }).join('');
}

function renderPastEvents() {
    const list = document.getElementById('pastEvents');
    const today = new Date();
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate(), 0, 0, 0);

    // Window: 7 days ago → yesterday
    const weekAgo = new Date(todayStart);
    weekAgo.setDate(todayStart.getDate() - 7);
    const yesterday = new Date(todayStart);
    yesterday.setDate(todayStart.getDate() - 1);
    yesterday.setHours(23, 59, 59, 999);

    const expanded = expandAppointments(appointments, weekAgo, yesterday)
        .filter(apt => apt.date < formatDateStr(todayStart))
        .sort((a, b) => b.date.localeCompare(a.date) || a.time.localeCompare(b.time));

    if (expanded.length === 0) {
        list.innerHTML = '<div class="no-appointments">Nenhum evento na última semana</div>';
        return;
    }

    list.innerHTML = expanded.map(apt => {
        const aptDate = new Date(`${apt.date}T${apt.time}`);
        const dateStr = aptDate.toLocaleDateString('pt-BR', { weekday: 'short', month: 'short', day: 'numeric' });
        const isReminder = apt.type === 'reminder';
        const isRecurring = apt._recurring;
        const cardClass = isRecurring ? 'appointment-card recurring-card'
            : (isReminder ? 'appointment-card reminder-card-style' : 'appointment-card');
        const icon = isRecurring ? '🔁' : (isReminder ? '⏰' : '📅');
        const recurBadge = isRecurring
            ? `<div class="recurrence-badge">🔁 ${FREQ_LABELS[apt.recurrence] || apt.recurrence}</div>`
            : '';

        return `
            <div class="${cardClass}">
                <div class="appointment-date">
                    <div class="date-large">${dateStr}</div>
                    <div class="time-large">${apt.time}</div>
                </div>
                <div class="appointment-details">
                    ${recurBadge}
                    ${getTitle(apt) ? `<div class="appointment-doctor">${getTitle(apt)}</div>` : ''}
                    ${apt.description && apt.description !== getTitle(apt) ? `<div class="appointment-description">${icon} ${apt.description}</div>` : `<div class="appointment-description">${icon}</div>`}
                    ${apt.location ? `<div class="appointment-location">📍 ${apt.location}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// Start the application
document.addEventListener('DOMContentLoaded', init);
