// Booking form
const form = document.getElementById('bookingForm');
const successMsg = document.getElementById('successMessage');
const dateInput = document.getElementById('date');
const timeSelect = document.getElementById('time');

// Set min date to today
if (dateInput) {
  const today = new Date().toISOString().split('T')[0];
  dateInput.setAttribute('min', today);

  // Load available slots when date changes
  dateInput.addEventListener('change', loadAvailableSlots);
}

// Load available slots
async function loadAvailableSlots() {
  const selectedDate = dateInput.value;
  if (!selectedDate) return;

  try {
    const response = await fetch(`/api/available-slots?date=${selectedDate}`);
    if (!response.ok) throw new Error('Failed to load slots');

    const data = await response.json();
    
    // Clear existing options
    timeSelect.innerHTML = '<option value="">--Select time--</option>';
    
    if (data.slots && data.slots.length > 0) {
      data.slots.forEach(slot => {
        const option = document.createElement('option');
        option.value = slot.time;
        option.textContent = `${slot.time}${slot.available ? '' : ' (Full)'}`;
        option.disabled = !slot.available;
        timeSelect.appendChild(option);
      });
    } else {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No slots available';
      option.disabled = true;
      timeSelect.appendChild(option);
    }
  } catch (error) {
    console.error('Error loading slots:', error);
  }
}

// Submit booking
if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(form);
    const data = {
      date: formData.get('date'),
      time: formData.get('time'),
      email: formData.get('email'),
      phone: formData.get('phone') || null
    };

    try {
      const response = await fetch('/api/booking', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const result = await response.json();

      if (response.ok) {
        successMsg.classList.remove('hidden');
        form.reset();
        setTimeout(() => successMsg.classList.add('hidden'), 5000);
      } else {
        alert(result.error || 'Booking failed');
      }
    } catch (error) {
      alert('An error occurred. Please try again.');
    }
  });
}

// Scroll reveal animations
const observerOptions = {
  threshold: 0.1,
  rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('revealed');
      observer.unobserve(entry.target);
    }
  });
}, observerOptions);

// Observe all sections and cards for scroll animation
document.addEventListener('DOMContentLoaded', () => {
  const elementsToReveal = document.querySelectorAll('.section, .card-grid, .maison, .booking');
  elementsToReveal.forEach(el => {
    el.classList.add('scroll-reveal');
    observer.observe(el);
  });
});

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
  anchor.addEventListener('click', function (e) {
    e.preventDefault();
    const target = document.querySelector(this.getAttribute('href'));
    if (target) {
      target.scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }
  });
});

// Add parallax effect to hero
window.addEventListener('scroll', () => {
  const hero = document.querySelector('.hero-media img, .hero-media video');
  if (hero) {
    const scrolled = window.pageYOffset;
    hero.style.transform = `translateY(${scrolled * 0.5}px) scale(${1 + scrolled * 0.0001})`;
  }
});
