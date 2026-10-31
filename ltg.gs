var SPREADSHEET_ID = "1OjiSEduUa9AibtbQUGG5z842HW_W6svcnPKkC89TdZs";
var FINANCE_SPREADSHEET_ID = "1Z8tCUXaDKQCPbNxWNDrjO45TwCxlVD87Me1TGJTBIao";
var SHEET_NAME = "信徒資料總表";
var RECEIPT_SHEET_NAME = "收據總表";
var RECEIPT_HEADERS = [
  "收據編號",
  "開立時間",
  "姓名",
  "地址",
  "辦理項目",
  "收到金額",
  "備註",
  "PDF連結",
  "主選項",
  "次選項",
  "類別",
  "選項人數",
  "系統備註",
  "經手人備註"
];
var INCOME_OPTIONS_SHEET_NAME = "收入科目金額";
var EXPENSE_OPTIONS_SHEET_NAME = "支出科目";
var INCOME_SHEET_NAME = "收入表";
var EXPENSE_SHEET_NAME = "支出表";
var INCOME_HEADERS = [
  "日期",
  "類別",
  "科目",
  "規格",
  "金額(元)",
  "姓名",
  "系統備註",
  "經手人備註",
  "備註",
  "收據編號"
];
var EXPENSE_HEADERS = [
  "日期",
  "類別",
  "科目",
  "規格",
  "金額(元)",
  "姓名",
  "系統備註",
  "經手人備註",
  "備註",
  "收據編號",
  "PDF連結"
];

function getBelieverSheet() {
  var spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = spreadsheet.getSheetByName(SHEET_NAME);

  if (!sheet) {
    throw new Error('找不到工作表「' + SHEET_NAME + '」，請確認分頁名稱。');
  }
  return sheet;
}

function jsonOutput(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function normalizeHeader(header) {
  return String(header).replace(/\s+/g, "");
}

function normalizeReceiptOptionHeader(header) {
  return normalizeHeader(header).replace(/[（(]元[）)]/g, "");
}

function getFinanceSpreadsheet() {
  return SpreadsheetApp.openById(FINANCE_SPREADSHEET_ID);
}

function getFinanceOptions(sheetName, incomeOptions) {
  var sheet = getFinanceSpreadsheet().getSheetByName(sheetName);
  if (!sheet) {
    throw new Error('找不到工作表「' + sheetName + '」。');
  }
  if (sheet.getLastRow() < 1 || sheet.getLastColumn() < 1) {
    throw new Error('工作表「' + sheetName + '」沒有標題列。');
  }

  var values = sheet.getDataRange().getValues();
  var headers = values[0].map(normalizeReceiptOptionHeader);
  var subjectColumn = headers.indexOf("科目");
  var specificationColumn = headers.indexOf("規格");
  var amountColumn = headers.indexOf("金額");
  if (subjectColumn === -1 || specificationColumn === -1 || amountColumn === -1) {
    throw new Error(
      '工作表「' + sheetName +
      '」標題列須包含「科目」、「規格」及「金額(元)」。'
    );
  }

  return values.slice(1).reduce(function(options, row) {
    var subject = String(row[subjectColumn] || "").trim();
    if (!subject) {
      return options;
    }
    if (incomeOptions) {
      options.push({
        "科目": subject,
        "規格": String(row[specificationColumn] || "").trim(),
        "金額": row[amountColumn]
      });
    } else {
      options.push({
        "科目": subject,
        "規格": String(row[specificationColumn] || "").trim(),
        "金額": row[amountColumn]
      });
    }
    return options;
  }, []);
}

function getFinanceLedgerSheet(sheetName, createIfMissing) {
  var spreadsheet = getFinanceSpreadsheet();
  var sheet = spreadsheet.getSheetByName(sheetName);
  var requiredHeaders = sheetName === EXPENSE_SHEET_NAME
    ? EXPENSE_HEADERS
    : INCOME_HEADERS;
  if (!sheet && createIfMissing) {
    sheet = spreadsheet.insertSheet(sheetName);
  }
  if (!sheet) {
    return null;
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(requiredHeaders);
    return sheet;
  }

  var headers = sheet
    .getRange(1, 1, 1, sheet.getLastColumn())
    .getValues()[0];
  requiredHeaders.forEach(function(requiredHeader) {
    var exists = headers.some(function(header) {
      return normalizeHeader(header) === normalizeHeader(requiredHeader);
    });
    if (!exists) {
      headers.push(requiredHeader);
      sheet.getRange(1, headers.length).setValue(requiredHeader);
    }
  });
  return sheet;
}

function getFinanceLedgerRecords(sheetName) {
  var sheet = getFinanceLedgerSheet(sheetName, false);
  if (!sheet || sheet.getLastRow() <= 1) {
    return [];
  }
  var data = sheet.getDataRange().getValues();
  var headers = data[0];
  return data.slice(1).map(function(row) {
    var record = {};
    headers.forEach(function(header, index) {
      var value = row[index];
      if (value instanceof Date) {
        value = Utilities.formatDate(
          value,
          Session.getScriptTimeZone(),
          "yyyy-MM-dd"
        );
      }
      record[normalizeHeader(header)] = value;
    });
    return record;
  });
}

function appendFinanceLedgerRecord(sheetName, values) {
  var sheet = getFinanceLedgerSheet(sheetName, true);
  var headers = sheet
    .getRange(1, 1, 1, sheet.getLastColumn())
    .getValues()[0];
  var rowNumber = sheet.getLastRow() + 1;
  sheet.appendRow(headers.map(function(header) {
    var value = values[normalizeHeader(header)];
    return value === undefined || value === null ? "" : value;
  }));
  return { sheet: sheet, rowNumber: rowNumber };
}

function validateFinanceAmount(amount) {
  var value = Number(amount);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("金額必須是大於或等於 0 的數字。");
  }
  return value;
}

function getReceiptSheet(spreadsheet) {
  var sheet = spreadsheet.getSheetByName(RECEIPT_SHEET_NAME);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(RECEIPT_SHEET_NAME);
  }
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(RECEIPT_HEADERS);
  } else {
    var headers = sheet
      .getRange(1, 1, 1, sheet.getLastColumn())
      .getValues()[0];
    var qrColumn = headers.findIndex(function(header) {
      return normalizeHeader(header) === "QR碼";
    }) + 1;
    if (qrColumn) {
      sheet.getImages().forEach(function(image) {
        if (image.getAnchorCell().getColumn() === qrColumn) {
          image.remove();
        }
      });
      sheet.deleteColumn(qrColumn);
      headers.splice(qrColumn - 1, 1);
    }
    RECEIPT_HEADERS.forEach(function(requiredHeader) {
      var hasHeader = headers.some(function(header) {
        return normalizeHeader(header) === normalizeHeader(requiredHeader);
      });
      if (!hasHeader) {
        headers.push(requiredHeader);
        sheet.getRange(1, headers.length).setValue(requiredHeader);
      }
    });
  }
  return sheet;
}

function isAuthorizedReceiptRequest(contents) {
  var expectedKey = PropertiesService.getScriptProperties()
    .getProperty("GAS_API_KEY");
  return Boolean(expectedKey && contents.apiKey === expectedKey);
}

function authorizeReceiptDriveAccess() {
  var authorizationFile = DriveApp.createFile(
    "LTG Drive authorization check",
    "Temporary file used to authorize receipt PDF creation."
  );
  authorizationFile.setTrashed(true);
}

function getReceiptRecords() {
  var spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = getReceiptSheet(spreadsheet);
  var data = sheet.getDataRange().getValues();
  if (data.length <= 1) {
    return [];
  }

  var headers = data[0];
  return data.slice(1).map(function(row) {
    var record = {};
    headers.forEach(function(header, index) {
      var value = row[index];
      if (value instanceof Date) {
        value = Utilities.formatDate(
          value,
          Session.getScriptTimeZone(),
          "yyyy-MM-dd HH:mm:ss"
        );
      }
      record[normalizeHeader(header)] = value;
    });
    if (record["選項人數"] === undefined && record["人數"] !== undefined) {
      record["選項人數"] = record["人數"];
    }
    if (record["科目"] === undefined && record["主選項"] !== undefined) {
      record["科目"] = record["主選項"];
    }
    if (record["規格"] === undefined && record["次選項"] !== undefined) {
      record["規格"] = record["次選項"];
    }
    return record;
  });
}

function getReceiptOptions() {
  return getFinanceOptions(INCOME_OPTIONS_SHEET_NAME, true);
}

function saveReceiptRecord(receipt, pdfBase64) {
  if (!receipt || !receipt["姓名"]) {
    throw new Error("收據姓名為必填欄位。");
  }
  var amount = Number(receipt["收到金額"]);
  if (!Number.isFinite(amount) || amount < 0) {
    throw new Error("收到金額必須是大於或等於 0 的數字。");
  }
  if (!pdfBase64) {
    throw new Error("缺少收執聯 PDF，收據未寫入。");
  }

  var spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = getReceiptSheet(spreadsheet);
  var headers = sheet
    .getRange(1, 1, 1, sheet.getLastColumn())
    .getValues()[0];
  var receiptId = String(receipt["收據編號"] || "");
  if (!/^LTG-\d{8}-\d{5}$/.test(receiptId)) {
    throw new Error("收據編號格式錯誤。");
  }
  var createdAt = String(receipt["開立時間"] || "");
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(createdAt)) {
    throw new Error("收據開立時間格式錯誤。");
  }

  var existingReceiptIds = sheet.getRange(
    2,
    1,
    Math.max(sheet.getLastRow() - 1, 1),
    1
  ).getValues();
  if (existingReceiptIds.some(function(row) {
    return String(row[0]) === receiptId;
  })) {
    throw new Error("收據編號重複，請重新產生收據。");
  }

  var record = {
    "收據編號": receiptId,
    "開立時間": createdAt,
    "姓名": String(receipt["姓名"]),
    "地址": String(receipt["地址"] || ""),
    "辦理項目": String(receipt["辦理項目"] || ""),
    "收到金額": amount,
    "備註": String(receipt["備註"] || ""),
    "主選項": String(receipt["主選項"] || ""),
    "次選項": String(receipt["次選項"] || ""),
    "類別": String(receipt["類別"] || ""),
    "選項人數": String(receipt["選項人數"] || receipt["人數"] || ""),
    "系統備註": String(receipt["系統備註"] || ""),
    "經手人備註": String(receipt["經手人備註"] || ""),
    "PDF連結": ""
  };

  var pdfFile;
  var rowNumber = 0;
  var financeAppend = null;
  try {
    var pdfBytes = Utilities.base64Decode(pdfBase64);
    var pdfBlob = Utilities.newBlob(
      pdfBytes,
      "application/pdf",
      receiptId + ".pdf"
    );
    pdfFile = DriveApp.createFile(pdfBlob);
    pdfFile.setSharing(DriveApp.Access.ANYONE, DriveApp.Permission.VIEW);
    record["PDF連結"] = pdfFile.getUrl();

    rowNumber = sheet.getLastRow() + 1;
    sheet.appendRow(headers.map(function(header) {
      var value = record[normalizeHeader(header)];
      return value === undefined || value === null ? "" : value;
    }));
    financeAppend = appendFinanceLedgerRecord(INCOME_SHEET_NAME, {
      "日期": createdAt.substring(0, 10),
      "類別": String(receipt["類別"] || ""),
      "科目": String(receipt["主選項"] || ""),
      "規格": String(receipt["次選項"] || ""),
      "金額(元)": amount,
      "姓名": String(receipt["姓名"]),
      "備註": String(receipt["經手人備註"] || receipt["備註"] || ""),
      "收據編號": receiptId
    });
  } catch (saveError) {
    if (
      financeAppend &&
      financeAppend.sheet.getLastRow() === financeAppend.rowNumber
    ) {
      financeAppend.sheet.deleteRow(financeAppend.rowNumber);
    }
    if (rowNumber && sheet.getLastRow() === rowNumber) {
      sheet.deleteRow(rowNumber);
    }
    if (pdfFile) {
      pdfFile.setTrashed(true);
    }
    throw new Error("收執聯 PDF 或總表寫入失敗：" + saveError.message);
  }

  return record;
}

function saveExpenseRecord(expense, pdfBase64) {
  if (!expense || !expense["科目"]) {
    throw new Error("支出科目為必填欄位。");
  }
  if (!expense["姓名"]) {
    throw new Error("支出收據姓名為必填欄位。");
  }
  if (!pdfBase64) {
    throw new Error("缺少支出收執聯 PDF，支出未寫入。");
  }
  var date = String(expense["日期"] || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error("支出日期格式錯誤。");
  }
  var amount = validateFinanceAmount(expense["金額(元)"]);
  var receiptId = String(expense["收據編號"] || "");
  if (!/^LTG-EXP-\d{8}-\d{5}$/.test(receiptId)) {
    throw new Error("支出收據編號格式錯誤。");
  }
  var expenseSheet = getFinanceSpreadsheet().getSheetByName(EXPENSE_SHEET_NAME);
  if (expenseSheet && expenseSheet.getLastRow() > 1) {
    var expenseHeaders = expenseSheet
      .getRange(1, 1, 1, expenseSheet.getLastColumn())
      .getValues()[0];
    var receiptColumn = expenseHeaders.findIndex(function(header) {
      return normalizeHeader(header) === "收據編號";
    });
    if (receiptColumn >= 0) {
      var existingReceiptIds = expenseSheet
        .getRange(
          2,
          receiptColumn + 1,
          expenseSheet.getLastRow() - 1,
          1
        )
        .getValues();
      if (existingReceiptIds.some(function(row) {
        return String(row[0]) === receiptId;
      })) {
        throw new Error("支出收據編號重複，請重新產生收據。");
      }
    }
  }
  var record = {
    "日期": date,
    "類別": String(expense["科目"]),
    "科目": String(expense["科目"]),
    "規格": String(expense["規格"] || ""),
    "金額(元)": amount,
    "姓名": String(expense["姓名"]),
    "系統備註": String(expense["系統備註"] || ""),
    "經手人備註": String(expense["經手人備註"] || ""),
    "備註": String(expense["備註"] || ""),
    "收據編號": receiptId,
    "PDF連結": ""
  };

  var pdfFile;
  var appended = null;
  try {
    var pdfBlob = Utilities.newBlob(
      Utilities.base64Decode(pdfBase64),
      "application/pdf",
      receiptId + ".pdf"
    );
    pdfFile = DriveApp.createFile(pdfBlob);
    pdfFile.setSharing(DriveApp.Access.ANYONE, DriveApp.Permission.VIEW);
    record["PDF連結"] = pdfFile.getUrl();
    appended = appendFinanceLedgerRecord(EXPENSE_SHEET_NAME, record);
  } catch (saveError) {
    if (
      appended &&
      appended.sheet.getLastRow() === appended.rowNumber
    ) {
      appended.sheet.deleteRow(appended.rowNumber);
    }
    if (pdfFile) {
      pdfFile.setTrashed(true);
    }
    throw new Error("支出收執聯 PDF 或支出表寫入失敗：" + saveError.message);
  }
  return record;
}

function doGet(e) {
  try {
    var sheet = getBelieverSheet();
    var data = sheet.getDataRange().getValues();

    if (data.length <= 1) {
      return jsonOutput([]);
    }

    var headers = data[0];
    var result = [];

    for (var i = 1; i < data.length; i++) {
      var row = data[i];
      var item = {};

      for (var j = 0; j < headers.length; j++) {
        var value = row[j];
        var header = normalizeHeader(headers[j]);
        if (value instanceof Date) {
          value = Utilities.formatDate(
            value,
            Session.getScriptTimeZone(),
            "yyyy-MM-dd"
          );
        }
        item[header] = value;
      }
      result.push(item);
    }

    return jsonOutput(result);
  } catch (err) {
    return jsonOutput({ status: "error", message: err.message });
  }
}

function doPost(e) {
  var lock;
  try {
    if (!e || !e.postData || !e.postData.contents) {
      throw new Error("缺少要寫入的資料。");
    }

    var contents = JSON.parse(e.postData.contents);
    if (contents.action === "listReceipts") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      return jsonOutput({ status: "success", records: getReceiptRecords() });
    }
    if (contents.action === "listReceiptOptions") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      return jsonOutput({
        status: "success",
        options: getReceiptOptions()
      });
    }
    if (contents.action === "listExpenseOptions") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      return jsonOutput({
        status: "success",
        options: getFinanceOptions(EXPENSE_OPTIONS_SHEET_NAME, false)
      });
    }
    if (contents.action === "listFinanceRecords") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      return jsonOutput({
        status: "success",
        income: getFinanceLedgerRecords(INCOME_SHEET_NAME),
        expenses: getFinanceLedgerRecords(EXPENSE_SHEET_NAME)
      });
    }

    lock = LockService.getScriptLock();
    lock.waitLock(30000);

    if (contents.action === "saveReceipt") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      var savedReceipt = saveReceiptRecord(
        contents.receipt,
        contents.pdfBase64
      );
      return jsonOutput({
        status: "success",
        message: "收據 PDF 已存入 Google Drive 並加入總表",
        record: savedReceipt
      });
    }
    if (contents.action === "saveExpense") {
      if (!isAuthorizedReceiptRequest(contents)) {
        throw new Error("收據總表 API 金鑰無效或未設定。");
      }
      return jsonOutput({
        status: "success",
        message: "支出已加入支出表",
        record: saveExpenseRecord(contents.expense, contents.pdfBase64)
      });
    }

    var sheet = getBelieverSheet();
    var lastColumn = sheet.getLastColumn();

    if (lastColumn < 1) {
      throw new Error("工作表沒有標題列，無法寫入資料。");
    }

    var headers = sheet.getRange(1, 1, 1, lastColumn).getValues()[0];
    var numberColumn = headers.findIndex(function(header) {
      return normalizeHeader(header) === "編號";
    });
    if (numberColumn === -1) {
      throw new Error("標題列找不到「編號」欄，無法自動編號。");
    }

    var maxNumber = 0;
    var lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      var existingNumbers = sheet
        .getRange(2, numberColumn + 1, lastRow - 1, 1)
        .getValues();
      existingNumbers.forEach(function(row) {
        var value = row[0];
        if (value !== "" && value !== null) {
          var number = Number(value);
          if (Number.isFinite(number) && Number.isInteger(number)) {
            maxNumber = Math.max(maxNumber, number);
          }
        }
      });
    }

    var newNumber = maxNumber + 1;
    var newRow = headers.map(function(header) {
      var normalizedHeader = normalizeHeader(header);
      if (normalizedHeader === "編號") {
        return newNumber;
      }
      return contents[normalizedHeader] !== undefined
        ? contents[normalizedHeader]
        : "";
    });

    sheet.appendRow(newRow);
    return jsonOutput({
      status: "success",
      message: "資料寫入成功",
      number: newNumber
    });
  } catch (err) {
    return jsonOutput({ status: "error", message: err.message });
  } finally {
    if (lock && lock.hasLock()) {
      lock.releaseLock();
    }
  }
}
