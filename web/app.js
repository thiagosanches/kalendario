// Doctor Appointment Calendar Application

let currentDate = new Date();
let appointments = [];
let viewMode = '7days'; // 'month' or '7days'
let startDate = new Date(); // For 7-day view

// Initialize the application
async function init() {
    updateCurrentDate();
    await loadAppointments();
    renderView();
    renderAppointmentsList();
    renderTodayReminders();
    updateRefreshTime();
    
    // Event listeners
    document.getElementById('prevPeriod').addEventListener('click', () => {
        if (viewMode === 'month') {
            currentDate.setMonth(currentDate.getMonth() - 1);
        } else {
            startDate.setDate(startDate.getDate() - 7);
        }
        renderView();
    });
    
    document.getElementById('nextPeriod').addEventListener('click', () => {
        if (viewMode === 'month') {
            currentDate.setMonth(currentDate.getMonth() + 1);
        } else {
            startDate.setDate(startDate.getDate() + 7);
        }
        renderView();
    });
    
    document.getElementById('monthViewBtn').addEventListener('click', () => {
        viewMode = 'month';
        document.getElementById('monthViewBtn').classList.add('active');
        document.getElementById('days15ViewBtn').classList.remove('active');
        renderView();
    });
    
    document.getElementById('days15ViewBtn').addEventListener('click', () => {
        viewMode = '7days';
        startDate = new Date(); // Reset to today
        document.getElementById('days15ViewBtn').classList.add('active');
        document.getElementById('monthViewBtn').classList.remove('active');
        renderView();
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
    renderTodayReminders();
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
    if (viewMode === 'month') {
        renderMonthCalendar();
    } else {
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
        
        // Check for appointments on this day
        const dayAppointments = appointments.filter(apt => apt.date === dateStr);
        
        dayCell.innerHTML = `
            <div class="day-number">${day}</div>
            ${dayAppointments.length > 0 ? `<div class="appointment-indicator">${dayAppointments.length}</div>` : ''}
        `;
        
        if (dayAppointments.length > 0) {
            dayCell.classList.add('has-appointment');
            dayCell.title = dayAppointments.map(apt => `${apt.time} - ${apt.doctor}`).join('\n');
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
        
        // Get appointments for this day
        const dayAppointments = appointments.filter(apt => apt.date === dateStr);
        dayAppointments.sort((a, b) => a.time.localeCompare(b.time));
        
        const dayNames = ['Domingo', 'Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado'];
        const dayName = dayNames[currentDay.getDay()];
        
        let appointmentsHTML = '';
        if (dayAppointments.length > 0) {
            appointmentsHTML = dayAppointments.map(apt => {
                const isReminder = apt.type === 'reminder';
                const cssClass = isReminder ? 'day-appointment reminder' : 'day-appointment';
                const icon = isReminder ? '⏰' : '🏥';
                
                return `
                <div class="${cssClass}">
                    <div class="day-apt-time">${icon} ${apt.time}</div>
                    <div class="day-apt-details">
                        ${apt.doctor ? `<div class="day-apt-doctor">${apt.doctor}</div>` : ''}
                        <div class="day-apt-desc">${apt.description}</div>
                        ${apt.location ? `<div class="day-apt-location">📍 ${apt.location}</div>` : ''}
                    </div>
                </div>
            `;
            }).join('');
        } else {
            appointmentsHTML = '<div class="no-appointments-day">Sem consultas ou lembretes</div>';
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
    
    // Sort appointments by date and time
    const sortedAppointments = [...appointments].sort((a, b) => {
        const dateA = new Date(`${a.date}T${a.time}`);
        const dateB = new Date(`${b.date}T${b.time}`);
        return dateA - dateB;
    });
    
    // Filter future appointments
    const now = new Date();
    const futureAppointments = sortedAppointments.filter(apt => {
        const aptDate = new Date(`${apt.date}T${apt.time}`);
        return aptDate >= now;
    });
    
    if (futureAppointments.length === 0) {
        list.innerHTML = '<div class="no-appointments">Nenhum lembrete agendado</div>';
        return;
    }
    
    list.innerHTML = futureAppointments.map(apt => {
        const aptDate = new Date(`${apt.date}T${apt.time}`);
        const dateStr = aptDate.toLocaleDateString('pt-BR', { weekday: 'short', month: 'short', day: 'numeric' });
        const isReminder = apt.type === 'reminder';
        const cardClass = isReminder ? 'appointment-card reminder-card-style' : 'appointment-card';
        
        return `
            <div class="${cardClass}">
                <div class="appointment-date">
                    <div class="date-large">${dateStr}</div>
                    <div class="time-large">${apt.time}</div>
                </div>
                <div class="appointment-details">
                    ${apt.doctor ? `<div class="appointment-doctor">${apt.doctor}</div>` : ''}
                    <div class="appointment-description">${isReminder ? '⏰ ' : '🏥 '}${apt.description}</div>
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
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
    
    const todayAppointments = appointments.filter(apt => apt.date === todayStr);
    
    if (todayAppointments.length === 0) {
        list.innerHTML = '<div class="no-reminders">Nenhum lembrete hoje</div>';
        return;
    }
    
    // Sort by time
    todayAppointments.sort((a, b) => a.time.localeCompare(b.time));
    
    list.innerHTML = todayAppointments.map(apt => {
        const isReminder = apt.type === 'reminder';
        const icon = isReminder ? '⏰' : '🏥';
        const cardClass = isReminder ? 'reminder-card reminder-type' : 'reminder-card';
        
        return `
        <div class="${cardClass}">
            <div class="reminder-time">${icon} ${apt.time}</div>
            <div class="reminder-details">
                ${apt.doctor ? `<div class="reminder-doctor">${apt.doctor}</div>` : ''}
                <div class="reminder-description">${apt.description}</div>
                ${apt.location ? `<div class="reminder-location">${apt.location}</div>` : ''}
            </div>
        </div>
    `;
    }).join('');
}

// Start the application
document.addEventListener('DOMContentLoaded', init);
