/* Eid al-Fitr (Sallah) Redesign Script */
(function () {
  "use strict";

  var form = document.getElementById("contact-form");
  var note = document.getElementById("contact-note");

  if (form && note) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      note.textContent = "Eid Mubarak! Sample only: this demo form does not send messages anywhere.";
      form.reset();
    });
  }
})();
