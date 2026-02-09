const form = document.querySelector(".booking-form");
const note = document.getElementById("booking-note");

if (form && note) {
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const date = data.get("pickup-date");
    const time = data.get("pickup-time");

    if (!date || !time) {
      note.textContent = "Please select a date and time to confirm.";
      return;
    }

    note.textContent = `Slot requested for ${date} at ${time}. We will confirm by email.`;
  });
}
