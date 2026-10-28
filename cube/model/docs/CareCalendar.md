# This is SQL statements use for CareCalendar reporting in EIS. We are trying to replicate this using cube. Ensure that all tables and fields as exposed.

SELECT createdon, calltype, ordercode, call_number 
FROM csrcalld 
WHERE year(csrcalld.createdon) = [yYear]
  AND month(csrcalld.createdon) = [mMonth]
ORDER BY createdon;

SELECT createdon, call_number, createdby, csrcalld.account_no, 
       csrcalld.occupant_code, name, scheduledon, order_no, 
       completedon, csrcalld.callstatus, csrctypr.description calldesc, csrstatc.shortdesc statdesc 
FROM csrcalld, pu_account, csrstatc, csrctypr 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [monthno]
  AND day(createdon) = [callday]
  AND csrcalld.account_no = pu_account.account_no 
  AND csrcalld.occupant_code = pu_account.occupant_code 
  AND csrcalld.callstatus = csrstatc.callstatus 
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
ORDER BY createdon;


SELECT createdon, call_number, createdby, csrcalld.account_no, 
       csrcalld.occupant_code, name, scheduledon, 
       completedon, csrcalld.callstatus, csrctypr.description calldesc, csrstatc.shortdesc statdesc 
FROM csrcalld, outer csrstatc, outer csrctypr, pu_account 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [monthno]
  AND day(createdon) = [callday]
  AND csrcalld.account_no = pu_account.account_no 
  AND csrcalld.occupant_code = pu_account.occupant_code 
  AND csrcalld.callstatus = csrstatc.callstatus 
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
ORDER BY createdon;


SELECT call_number, sequence_no, notes 
FROM csrschdd 
WHERE call_number = [l_callnumber]
ORDER BY sequence_no;

SELECT call_number, sequence_no, notes 
FROM csrcmpld 
WHERE call_number = [l_callnumber]
ORDER BY sequence_no;

