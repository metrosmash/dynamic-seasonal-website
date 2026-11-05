/* Shell behaviour for the seasonal redesign demo page. */
(function () {
  "use strict";

  var stateNode = document.getElementById("seasonal-state");
  var state = { season: "Original", history: ["Original"], index: 0, can_back: false, can_forward: false };
  try {
    if (stateNode) {
      state = JSON.parse(stateNode.textContent);
    }
  } catch (error) {
    state = { season: "Original", history: ["Original"], index: 0, can_back: false, can_forward: false };
  }

  var status = document.getElementById("status");
  var historyLine = document.getElementById("history-line");
  var frame = document.getElementById("preview");
  var backButton = document.getElementById("back-button");
  var forwardButton = document.getElementById("forward-button");
  var resetButton = document.getElementById("reset-button");
  var customForm = document.getElementById("custom-form");
  var customInput = document.getElementById("custom-season");
  var presetButtons = Array.prototype.slice.call(document.querySelectorAll(".preset"));

  function setBusy(busy) {
    var controls = presetButtons.concat([backButton, forwardButton, resetButton]);
    controls.forEach(function (button) {
      if (button) {
        button.disabled = busy;
      }
    });
    var submit = customForm ? customForm.querySelector("button[type='submit']") : null;
    if (submit) {
      submit.disabled = busy;
    }
    if (customInput) {
      customInput.disabled = busy;
    }
  }

  function render(message, isError) {
    if (status) {
      status.classList.toggle("error", Boolean(isError));
      if (message) {
        status.textContent = message;
      } else {
        status.textContent = "";
        var number = document.createElement("span");
        number.className = "edition-no";
        number.textContent = "Edition " + (state.index + 1) + " of " + state.history.length;
        status.appendChild(number);
        status.appendChild(document.createTextNode(" \u00B7 " + state.season));
      }
    }
    if (historyLine) {
      historyLine.textContent = state.history.join(" \u2192 ");
    }
    presetButtons.forEach(function (button) {
      button.classList.toggle("active", button.getAttribute("data-season") === state.season);
    });
    if (backButton) {
      backButton.disabled = !state.can_back;
    }
    if (forwardButton) {
      forwardButton.disabled = !state.can_forward;
    }
  }

  function reloadPreview() {
    if (frame) {
      frame.src = "/preview?v=" + Date.now();
    }
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : "{}"
    }).then(function (response) {
      return response.json().then(function (payload) {
        return { ok: response.ok, payload: payload };
      });
    });
  }

  function applySeason(season) {
    setBusy(true);
    render("Asking the agent to redesign the site for " + season + "…", false);
    post("/api/redesign", { season: season }).then(function (result) {
      if (result.ok) {
        state = result.payload;
        reloadPreview();
        render(state.warning || "", false);
      } else {
        render("Redesign failed; kept the previous version. " +
          (result.payload.error || "Unknown error."), true);
      }
    }).catch(function () {
      render("Redesign failed; kept the previous version. Network error.", true);
    }).finally(function () {
      setBusy(false);
      render(status.classList.contains("error") ? status.textContent : "", status.classList.contains("error"));
    });
  }

  presetButtons.forEach(function (button) {
    button.addEventListener("click", function () {
      applySeason(button.getAttribute("data-season"));
    });
  });

  if (customForm) {
    customForm.addEventListener("submit", function (event) {
      event.preventDefault();
      var season = customInput.value.trim();
      if (!season) {
        render("Enter a season name first.", true);
        return;
      }
      applySeason(season);
    });
  }

  if (resetButton) {
    resetButton.addEventListener("click", function () {
      setBusy(true);
      post("/api/reset", null).then(function (result) {
        if (result.ok) {
          state = result.payload;
          reloadPreview();
          render("Restored the original site.", false);
        } else {
          render("Reset failed. " + (result.payload.error || "Unknown error."), true);
        }
      }).catch(function () {
        render("Reset failed. Network error.", true);
      }).finally(function () {
        setBusy(false);
        render(status.classList.contains("error") ? status.textContent : "", status.classList.contains("error"));
      });
    });
  }

  function step(url) {
    setBusy(true);
    post(url, null).then(function (result) {
      if (result.ok) {
        state = result.payload;
        reloadPreview();
        render("", false);
      } else {
        render("History step failed. " + (result.payload.error || "Unknown error."), true);
      }
    }).catch(function () {
      render("History step failed. Network error.", true);
    }).finally(function () {
      setBusy(false);
      render(status.classList.contains("error") ? status.textContent : "", status.classList.contains("error"));
    });
  }

  if (backButton) {
    backButton.addEventListener("click", function () { step("/api/back"); });
  }
  if (forwardButton) {
    forwardButton.addEventListener("click", function () { step("/api/forward"); });
  }

  render("", false);
})();
