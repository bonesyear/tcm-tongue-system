function initConstitutionWizard() {
  var dialog = document.getElementById("constitution-modal");
  if (!dialog) return;
  var assessment = STATE.constitution_assessment || {
    status: "new", gender: null, answers: {}, unanswered: [], evaluation: null,
  };
  var busy = false;
  var options = {
    1: "没有（根本不）", 2: "很少（有一点）", 3: "有时（有些）",
    4: "经常（相当）", 5: "总是（非常）",
  };
  var errorBox = document.getElementById("constitution-error");

  function applicable(entry) {
    return (entry.gender_condition === "female_only" && assessment.gender === "female") ||
      (entry.gender_condition === "male_only" && assessment.gender === "male") ||
      entry.gender_condition === "all";
  }

  function answeredCount() {
    return CONSTITUTION_RULES.filter(function (entry) {
      return applicable(entry) && assessment.answers[entry.entry_id];
    }).length + CONSTITUTION_RULES.filter(function (entry) {
      return applicable(entry) && assessment.unanswered.indexOf(entry.entry_id) >= 0;
    }).length;
  }

  function applicableCount() {
    return CONSTITUTION_RULES.filter(applicable).length;
  }

  function element(tag, text, className) {
    var node = document.createElement(tag);
    node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function choice(text, pressed, disabled, label, onClick) {
    var button = element("button", text, "constitution-choice");
    button.type = "button";
    button.setAttribute("aria-pressed", String(pressed));
    button.setAttribute("aria-label", label);
    button.disabled = disabled;
    button.addEventListener("click", onClick);
    return button;
  }

  function save(payload) {
    if (busy) return;
    busy = true;
    errorBox.style.display = "none";
    errorBox.textContent = "";
    render();
    postJSON("/wizard/constitution", payload).then(function (data) {
      assessment = data.assessment || {
        status: "new", gender: null, answers: {}, unanswered: [], evaluation: null,
      };
    }).catch(function (error) {
      errorBox.textContent = error && error.message ? error.message : String(error);
      errorBox.style.display = "";
    }).finally(function () {
      busy = false;
      render();
    });
  }

  function answer(entry, value) {
    if (busy || !applicable(entry)) return;
    var previous = assessment.answers[entry.entry_id];
    var next = Object.assign({}, assessment);
    next.answers = Object.assign({}, assessment.answers);
    next.unanswered = (assessment.unanswered || []).filter(function (id) {
      return id !== entry.entry_id;
    });
    if (previous === value) {
      delete next.answers[entry.entry_id];
      save({action: "clear_answer", entry_id: entry.entry_id});
    } else {
      next.answers[entry.entry_id] = value;
      save({action: "answer", entry_id: entry.entry_id, value: value});
    }
    assessment = next;
    render();
  }

  function unknown(entry) {
    if (busy || !applicable(entry)) return;
    var next = Object.assign({}, assessment);
    next.answers = Object.assign({}, assessment.answers);
    delete next.answers[entry.entry_id];
    var wasUnknown = assessment.unanswered.indexOf(entry.entry_id) >= 0;
    next.unanswered = (assessment.unanswered || []).filter(function (id) {
      return id !== entry.entry_id;
    });
    if (!wasUnknown) next.unanswered.push(entry.entry_id);
    assessment = next;
    render();
    save({action: wasUnknown ? "clear_answer" : "unanswered", entry_id: entry.entry_id});
  }

  function render() {
    dialog.querySelectorAll("[data-gender]").forEach(function (button) {
      var selected = button.getAttribute("data-gender") === assessment.gender;
      button.setAttribute("aria-pressed", String(selected));
      button.disabled = busy;
    });
    var progress = document.getElementById("constitution-progress");
    if (!assessment.gender) {
      progress.textContent = "请先选择男性或女性，再开始评估。";
    } else {
      var labels = {draft: "草稿", completed: "已完成", skipped: "已整体跳过", new: "未开始"};
      progress.textContent = "当前性别适用 " + applicableCount() + " 项，已处理 " + answeredCount() +
        " 项 · " + (labels[assessment.status] || "草稿") + " · 未处理项不作正常或平和。";
    }

    var groups = {};
    CONSTITUTION_RULES.forEach(function (entry) {
      if (!groups[entry.constitution]) groups[entry.constitution] = [];
      groups[entry.constitution].push(entry);
    });
    var container = document.getElementById("constitution-questions");
    container.replaceChildren();
    Object.keys(groups).forEach(function (constitution) {
      var fieldset = element("fieldset", "", "constitution-group");
      fieldset.appendChild(element("legend", constitution));
      groups[constitution].forEach(function (entry) {
        var item = element("div", "", "constitution-item");
        item.setAttribute("data-entry-id", entry.entry_id);
        var question = element("div", "", "constitution-question");
        question.textContent = entry.question;
        question.appendChild(element("span", entry.source_clause + " · PDF " +
          entry.source_pdf_page, "constitution-source"));
        item.appendChild(question);
        if (!applicable(entry)) {
          item.appendChild(element("div", "当前性别不适用，不计入。", "constitution-unavailable"));
        }
        var choices = element("div", "", "constitution-choices");
        Object.keys(options).forEach(function (value) {
          var label = entry.question + "，" + options[value];
          choices.appendChild(choice(value + " · " + options[value],
            assessment.answers[entry.entry_id] === value,
            busy || !assessment.gender || !applicable(entry), label,
            function () { answer(entry, value); }));
        });
        choices.appendChild(choice("无法回答",
          assessment.unanswered.indexOf(entry.entry_id) >= 0,
          busy || !assessment.gender || !applicable(entry),
          entry.question + "，无法回答", function () { unknown(entry); }));
        item.appendChild(choices);
        fieldset.appendChild(item);
      });
      container.appendChild(fieldset);
    });

    var summary = document.getElementById("constitution-summary");
    summary.replaceChildren();
    if (assessment.status === "skipped") {
      summary.appendChild(element("p", "已整体跳过，未生成体质结果。", "alert-note"));
    } else if (assessment.evaluation) {
      var unknowns = assessment.evaluation.unknown.categories;
      if (unknowns.length) {
        summary.appendChild(element("p", "未知类别：" + unknowns.join("、") +
          "；证据不足，不自动选择体质食养。", "alert-note"));
      }
      var combined = assessment.evaluation.combined_results;
      if (combined.length) {
        var list = element("ul");
        combined.forEach(function (item) {
          list.appendChild(element("li", item.constitution + "：" + item.result +
            "（转化分 " + item.display_score + "，" + item.source_clause +
            "，PDF " + item.source_pdf_page + "）"));
        });
        summary.appendChild(list);
      } else if (!unknowns.length) {
        summary.appendChild(element("p", "没有达到“是”或“倾向是”的偏颇类型；这不等同于已判定为平和。", "muted"));
      }
    }
  }

  document.getElementById("constitution-open").addEventListener("click", function () {
    render();
    dialog.showModal();
  });
  dialog.querySelectorAll("[data-gender]").forEach(function (button) {
    button.addEventListener("click", function () {
      if (!busy) assessment = Object.assign({}, assessment, {gender: button.getAttribute("data-gender")});
      render();
      if (!busy) save({action: "gender", gender: button.getAttribute("data-gender")});
    });
  });
  document.getElementById("constitution-clear").addEventListener("click", function () {
    if (!busy && confirm("仅清除本次国标体质评估，保留其他观察与六经问诊。确定？")) {
      save({action: "clear"});
    }
  });
  document.getElementById("constitution-skip").addEventListener("click", function () {
    if (!busy && assessment.status !== "skipped" &&
        confirm("整体跳过后不生成体质评估结果，其他记录保留。确定？")) {
      save({action: "skip"});
    }
  });
  render();
}
