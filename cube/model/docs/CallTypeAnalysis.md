# Purpose : Aggregates call counts by year, call type, and call type descriptions for specific year. 
SELECT year(createdon) sel_year, csrcalld.calltype, csrctypr.description calldesc, count(*) amount 
FROM csrcalld, csrctypr 
WHERE year(createdon) = [l_year]
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
GROUP BY year(createdon), csrcalld.calltype, csrctypr.description 
ORDER BY year(createdon), csrcalld.calltype, csrctypr.description;

# Purpose : Aggregates call counts by year, call type, and call type descriptions for specific year and month.
SELECT year(createdon) sel_year, csrcalld.calltype, csrctypr.description calldesc, count(*) amount 
FROM csrcalld, csrctypr 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [l_month]
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
GROUP BY year(createdon), csrcalld.calltype, csrctypr.description 
ORDER BY year(createdon), csrcalld.calltype, csrctypr.description;

# Purpose : Aggregates call counts by year and month for a specific year and call type. 
SELECT year(createdon) sel_year, month(createdon) sel_month, count(*) amount 
FROM csrcalld 
WHERE year(createdon) = [l_year]
  AND calltype = '[l_csr]'
GROUP BY year(createdon), month(createdon) 
ORDER BY year(createdon), month(createdon);

# Purpose : Aggregates call counts by day, year, month for a specific year, month, and call type.
SELECT year(createdon) sel_year, month(createdon) sel_month, day(createdon) sel_day, count(*) amount 
FROM csrcalld 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [monthno]
  AND calltype = '[l_csr]'
GROUP BY year(createdon), month(createdon), day(createdon) 
ORDER BY year(createdon), month(createdon), day(createdon);

# Purpose: Returns the count of calls for a specific date (year, month, day) and call type.
SELECT year(createdon) sel_year, month(createdon) sel_month, day(createdon) sel_day, count(*) amount 
FROM csrcalld 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [monthno]
  AND day(createdon) = [DayofMonth]
  AND calltype = '[l_csr]'
GROUP BY year(createdon), month(createdon), day(createdon) 
ORDER BY year(createdon), month(createdon), day(createdon);

# Purpose: Returns detailed call records for a specific date and call type.
SELECT createdon, createdby, csrcalld.account_no, csrcalld.occupant_code, name, scheduledon, 
       completedon, csrcalld.callstatus, csrctypr.shortdesc calldesc, csrstatc.shortdesc statdesc 
FROM csrcalld, csrstatc, csrctypr, pu_account 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [l_month]
  AND day(createdon) = [l_day]
  AND csrcalld.calltype = '[l_calltype]'
  AND csrcalld.account_no = pu_account.account_no 
  AND csrcalld.occupant_code = pu_account.occupant_code 
  AND csrcalld.callstatus = csrstatc.callstatus 
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
ORDER BY createdon;

# Purpose: Aggregates call counts by call type for a specific year and month.
SELECT year(createdon) sel_year, csrcalld.calltype, csrctypr.description calldesc, count(*) amount 
FROM csrcalld, csrctypr 
WHERE year(createdon) = [l_year]
  AND month(createdon) = [l_month]
  AND csrcalld.callcode = csrctypr.callcode 
  AND csrcalld.calltype = csrctypr.calltype 
GROUP BY 1, 2, 3 
ORDER BY 1, 2, 3;