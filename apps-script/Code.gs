/**
 * LoseIt Sync receiver. Deploy as a web app ("Execute as: Me", "Who has access: Anyone").
 * The Android app POSTs Health Connect nutrition + weight rows here; they land in a Google
 * Sheet in your Drive that Claude reads through the Google Drive connector.
 *
 * First run: select setup() and click Run. It creates the sheet and logs your sync token.
 */

var SHEET_NAME = 'LoseIt Sync (Health Connect)';
var TEXT_COLUMNS = ['id', 'date', 'time', 'meal', 'name', 'source'];

function setup() {
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SYNC_TOKEN')) {
    props.setProperty('SYNC_TOKEN', Utilities.getUuid());
  }
  var ss = getSpreadsheet_();
  Logger.log('Sheet: ' + ss.getUrl());
  Logger.log('Sync token (paste into the app): ' + props.getProperty('SYNC_TOKEN'));
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  try {
    var body = JSON.parse(e.postData.contents);
    var token = PropertiesService.getScriptProperties().getProperty('SYNC_TOKEN');
    if (!token || body.token !== token) return reply_({ ok: false, error: 'bad token' });
    if (!/^\d{4}-\d{2}-\d{2}$/.test(body.rangeStart) || !/^\d{4}-\d{2}-\d{2}$/.test(body.rangeEnd)) {
      return reply_({ ok: false, error: 'bad date range' });
    }

    lock.waitLock(60000);
    var ss = getSpreadsheet_();
    var tz = body.timezone || ss.getSpreadsheetTimeZone();
    var food = replaceRange_(ss, 'food_log', body.nutrition, body.rangeStart, body.rangeEnd, tz);
    var weight = replaceRange_(ss, 'weight', body.weight, body.rangeStart, body.rangeEnd, tz);
    rebuildDailyTotals_(ss, tz);
    ss.getSheetByName('sync_info').getRange('A1:B3').setValues([
      ['last_sync', new Date().toISOString()],
      ['last_range', body.rangeStart + ' to ' + body.rangeEnd],
      ['timezone', tz],
    ]);
    return reply_({ ok: true, foodRows: food, weightRows: weight });
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function getSpreadsheet_() {
  var props = PropertiesService.getScriptProperties();
  var id = props.getProperty('SHEET_ID');
  var ss = id ? SpreadsheetApp.openById(id) : null;
  if (!ss) {
    ss = SpreadsheetApp.create(SHEET_NAME);
    props.setProperty('SHEET_ID', ss.getId());
    ss.getSheets()[0].setName('daily_totals');
    ss.insertSheet('food_log');
    ss.insertSheet('weight');
    ss.insertSheet('sync_info');
  }
  return ss;
}

/** Drops every row dated within [start, end] and appends the incoming rows, merging new columns. */
function replaceRange_(ss, sheetName, table, start, end, tz) {
  var sheet = ss.getSheetByName(sheetName);
  var existing = readTable_(sheet, tz);
  var header = existing.header.length ? existing.header : table.columns.slice();
  table.columns.forEach(function (c) { if (header.indexOf(c) < 0) header.push(c); });

  var dateIdx = header.indexOf('date');
  var kept = existing.rows
    .map(function (row) { return realign_(row, existing.header, header); })
    .filter(function (row) { var d = row[dateIdx]; return d < start || d > end; });
  var incoming = table.rows.map(function (row) { return realign_(row, table.columns, header); });

  var all = kept.concat(incoming);
  all.sort(function (a, b) {
    return (a[dateIdx] + a[header.indexOf('time')]).localeCompare(b[dateIdx] + b[header.indexOf('time')]);
  });
  writeTable_(sheet, header, all);
  return incoming.length;
}

function rebuildDailyTotals_(ss, tz) {
  var food = readTable_(ss.getSheetByName('food_log'), tz);
  var weight = readTable_(ss.getSheetByName('weight'), tz);
  var numeric = food.header.filter(function (c) { return TEXT_COLUMNS.indexOf(c) < 0; });
  var dateIdx = food.header.indexOf('date');

  var byDate = {};
  food.rows.forEach(function (row) {
    var d = row[dateIdx];
    var t = byDate[d] || (byDate[d] = { entries: 0, sums: numeric.map(function () { return null; }) });
    t.entries++;
    numeric.forEach(function (c, i) {
      var v = row[food.header.indexOf(c)];
      if (v !== '' && v !== null && !isNaN(v)) t.sums[i] = (t.sums[i] || 0) + Number(v);
    });
  });

  // Last weigh-in of each day.
  var weightByDate = {};
  var wDate = weight.header.indexOf('date');
  var wLb = weight.header.indexOf('weight_lb');
  weight.rows.forEach(function (row) { if (wDate >= 0) weightByDate[row[wDate]] = row[wLb]; });

  var dates = Object.keys(byDate).concat(Object.keys(weightByDate))
    .filter(function (d, i, arr) { return d && arr.indexOf(d) === i; })
    .sort();
  var header = ['date', 'food_entries', 'weight_lb'].concat(numeric);
  var rows = dates.map(function (d) {
    var t = byDate[d] || { entries: 0, sums: numeric.map(function () { return null; }) };
    return [d, t.entries, weightByDate[d] === undefined ? '' : weightByDate[d]]
      .concat(t.sums.map(function (v) { return v === null ? '' : Math.round(v * 100) / 100; }));
  });
  writeTable_(ss.getSheetByName('daily_totals'), header, rows);
}

function readTable_(sheet, tz) {
  var values = sheet.getDataRange().getValues();
  if (values.length === 0 || values[0].join('') === '') return { header: [], rows: [] };
  var header = values[0].map(String);
  var rows = values.slice(1).map(function (row) {
    return row.map(function (v, i) {
      // Guard against Sheets having turned a text date/time into a Date.
      if (v instanceof Date) return Utilities.formatDate(v, tz, header[i] === 'time' ? 'HH:mm' : 'yyyy-MM-dd');
      return v;
    });
  });
  return { header: header, rows: rows };
}

function writeTable_(sheet, header, rows) {
  sheet.clearContents();
  var data = [header].concat(rows.map(function (r) {
    return r.map(function (v) { return v === null || v === undefined ? '' : v; });
  }));
  // Keep id/date/time/text columns as plain text so Sheets doesn't reinterpret them.
  header.forEach(function (c, i) {
    if (TEXT_COLUMNS.indexOf(c) >= 0) sheet.getRange(1, i + 1, data.length, 1).setNumberFormat('@');
  });
  sheet.getRange(1, 1, data.length, header.length).setValues(data);
  sheet.setFrozenRows(1);
}

function realign_(row, fromHeader, toHeader) {
  return toHeader.map(function (c) {
    var i = fromHeader.indexOf(c);
    return i < 0 || row[i] === null || row[i] === undefined ? '' : row[i];
  });
}
