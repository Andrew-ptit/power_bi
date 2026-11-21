"use strict";

// The add-in is served as ordered classic scripts, so a Node harness must see the
// same concatenation in the same order. Keeping the list here means a split or a
// rename is a one-line change for every harness instead of fourteen.

const fs = require("node:fs");
const path = require("node:path");

const DIR = path.join(__dirname, "../../pbip_assistant/excel_addin");
const ORDER = [
  "taskpane_core.js",
  "taskpane_flow.js",
  "taskpane_workspace.js",
  "taskpane_problem_chain.js",
  "taskpane_typed_pq.js",
  "taskpane.js",
];

function taskpaneSource() {
  return ORDER.map(name => fs.readFileSync(path.join(DIR, name), "utf8")).join("\n");
}

taskpaneSource.ORDER = ORDER;
taskpaneSource.DIR = DIR;

module.exports = taskpaneSource;
