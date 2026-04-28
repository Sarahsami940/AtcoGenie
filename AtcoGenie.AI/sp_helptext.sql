CREATE  PROCEDURE [dbo].[Sp_PharmaCRM_SVT]
    @Param_GroupId nvarchar(max) ,
    @Param_TeamId nvarchar(max)  ,
    @Param_ProductId nvarchar(max)  ,
    @Param_TerritoryId nvarchar(max) ,
    @Param_RegionId nvarchar(max)  ,
    @Param_DistrictId nvarchar(max)  ,
	@Param_SalesChannel nvarchar(max) ,
 	@Param_IsActualPrice bit  ,
    @Param_InvoiceDate_From DateTime,
    @Param_InvoiceDate_To DateTime,
	@EmpID int=0,
	@Param_MonthID int=1,
	@Param_SalesType nvarchar(max)='',
	@UserRole nvarchar(max)=''
	
AS
BEGIN
		
		Declare @Param_SalesTypeDescription nvarchar(100)
		if (@Param_TerritoryId='null' or @Param_TerritoryId is null or @Param_TerritoryId='')
		BEGIN	
			Exec Sp_PharmaCRM_GetEmployeeRoleSpecificTerritoryData 1,@EmpID,@UserRole
			SELECT @Param_TerritoryId=STRING_AGG(TerritoryID, ', ') 
			FROM ##TerritoryIds
			DROP TABLE IF EXISTS ##TerritoryIds;
		END
		IF @Param_SalesType = '0,1,2'
				Set @Param_SalesType=null;
		
		IF @Param_SalesType = '1'
		BEGIN
				SET @Param_SalesTypeDescription = 'Allocated Sale';
		END
		ELSE IF @Param_SalesType = '2'
			BEGIN
				SET @Param_SalesTypeDescription = 'Unallocated Sale';
			END
		ELSE
		BEGIN
				SET @Param_SalesTypeDescription = 'Allocated Sale,Unallocated Sale';
		END
		
		IF @Param_SalesChannel = '1'
		BEGIN
			SET @Param_SalesChannel = 'Trade';
		END
		ELSE IF @Param_SalesChannel = '2'
			BEGIN
				SET @Param_SalesChannel = 'Institution';
			END
		ELSE
		BEGIN
				SET @Param_SalesChannel = NULL;

		END
		
		--if (@Param_SalesChannel='null')  
		--Set @Param_SalesChannel=''
		DROP TABLE IF EXISTS #TeamIds
		CREATE TABLE #TeamIds (TeamId INT,RegionID INT default 0,DistrictID INT default 0,TerritoryID INT default 0,ProducID nvarchar(50),BrandID nvarchar(50)) ;
		
		CREATE NONCLUSTERED INDEX IDX_TeamIds
		ON #TeamIds (TeamId, RegionID, DistrictID, TerritoryID, ProducID, BrandID);
		


		if (@Param_SalesType='1')		-----Allocated Sale
		BEGIN
			INSERT INTO #TeamIds (TeamId,RegionID,DistrictID,TerritoryID,ProducID,BrandID)
			SELECT a.TeamId,a.RegionID,a.DistrictID,a.TerritoryID,a.ProductID,a.BrandID FROM Vw_TerritorySalesVstargetData a WHERE 1 = 1 AND cast(a.Compcode as int) = 1
			AND (a.TeamId IN (SELECT value FROM dbo.split(@Param_TeamId, ',')) OR isnull(@Param_TeamId,'') = '')
			AND (a.RegionId IN (SELECT value FROM dbo.split(@Param_RegionId, ',')) OR isnull(@Param_RegionId,'') = '') 
			AND (a.DistrictId IN (SELECT value FROM dbo.split(@Param_DistrictId, ',')) OR isnull(@Param_DistrictId,'') = '') 
			AND (a.TerritoryId IN (SELECT value FROM dbo.split(@Param_TerritoryId, ',')) OR isnull(@Param_TerritoryId,'') = '') 
			AND (a.BrandID IN (SELECT value FROM dbo.split(@Param_GroupId, ',')) OR isnull(@Param_GroupId,'') = '')
			AND (a.ProductID IN (SELECT value FROM dbo.split(@Param_ProductId, ',')) OR isnull(@Param_ProductId,'') = '')
		END
		else if (@Param_SalesType='2')  -----UnAllocated Sale 
		BEGIN
			INSERT INTO #TeamIds (TeamId,RegionID,DistrictID,TerritoryID,ProducID,BrandID)
			SELECT Distinct a.TeamId,RegionID=0,DistrictID=0,TerritoryID=0,a.ProductID,a.BrandID FROM Vw_TerritorySalesVstargetData a WHERE 1 = 1 AND cast(a.Compcode as int) = 1
			AND (a.TeamId IN (SELECT value FROM dbo.split(@Param_TeamId, ',')) OR isnull(@Param_TeamId,'') = '')
			AND (a.BrandID IN (SELECT value FROM dbo.split(@Param_GroupId, ',')) OR isnull(@Param_GroupId,'') = '') 
			AND (a.ProductID IN (SELECT value FROM dbo.split(@Param_ProductId, ',')) OR isnull(@Param_ProductId,'') = '') 
		END
		else							---- ALL
		BEGIN
				INSERT INTO #TeamIds (TeamId,RegionID,DistrictID,TerritoryID,ProducID,BrandID)
				SELECT a.TeamId,a.RegionID,a.DistrictID,a.TerritoryID,a.ProductID,a.BrandID FROM Vw_TerritorySalesVstargetData a WHERE 1 = 1 AND cast(a.Compcode as int) = 1
				AND (a.TeamId IN (SELECT value FROM dbo.split(@Param_TeamId, ',')) OR isnull(@Param_TeamId,'') = '')
				AND (a.RegionId IN (SELECT value FROM dbo.split(@Param_RegionId, ',')) OR isnull(@Param_RegionId,'') = '') 
				AND (a.DistrictId IN (SELECT value FROM dbo.split(@Param_DistrictId, ',')) OR isnull(@Param_DistrictId,'') = '') 
				AND (a.TerritoryId IN (SELECT value FROM dbo.split(@Param_TerritoryId, ',')) OR isnull(@Param_TerritoryId,'') = '') 
				AND (a.BrandID IN (SELECT value FROM dbo.split(@Param_GroupId, ',')) OR isnull(@Param_GroupId,'') = '')
				AND (a.ProductID IN (SELECT value FROM dbo.split(@Param_ProductId, ',')) OR isnull(@Param_ProductId,'') = '')
				UNION 
				SELECT Distinct a.TeamId,RegionID=0,DistrictID=0,TerritoryID=0,a.ProductID,a.BrandID FROM Vw_TerritorySalesVstargetData a WHERE 1 = 1 AND cast(a.Compcode as int) = 1
				AND (a.TeamId IN (SELECT value FROM dbo.split(@Param_TeamId, ',')) OR isnull(@Param_TeamId,'') = '')
				AND (a.BrandID IN (SELECT value FROM dbo.split(@Param_GroupId, ',')) OR isnull(@Param_GroupId,'') = '')
				AND (a.ProductID IN (SELECT value FROM dbo.split(@Param_ProductId, ',')) OR isnull(@Param_ProductId,'') = '')

		END

		--Select count(*) from #TeamIds

		--return

		
		DECLARE @FiscalYearStartMonth INT = 7; -- July is the fiscal year start
		DECLARE @CurrentYear INT = YEAR(@Param_InvoiceDate_From);
		DECLARE @StartDate DATE;
		DECLARE @EndDate DATE;

		-- Calculate start and end dates for the fiscal range
		
		SET @StartDate = DATEFROMPARTS(@CurrentYear, @FiscalYearStartMonth, 1); -- Start of fiscal year
		SET @EndDate = DATEADD(DAY, -1, DATEADD(MONTH, @Param_MonthID - @FiscalYearStartMonth + 1, @StartDate)); -- End of the desired month

		-- If MonthID < Start Month, handle crossing into the next calendar year
		IF @Param_MonthID < @FiscalYearStartMonth
		BEGIN
			SET @StartDate = DATEFROMPARTS(@CurrentYear, @FiscalYearStartMonth, 1); -- Start of fiscal year
			SET @EndDate = DATEADD(DAY, -1, DATEADD(MONTH, @Param_MonthID + 12 - @FiscalYearStartMonth + 1, @StartDate)); -- End of the desired month
		END;
		
		--Select @StartDate
		--Select @EndDate

		DROP TABLE IF EXISTS #Distributors;
		-- Create a temporary table to hold distributors with their finalized dates
			SELECT 
				DistributorID, 
				Distributor, 
				LastFinalizedDate = MAX(LastFinalizedDate)
			INTO #Distributors
			FROM ss_DistributorMonthWiseFinalizedDate
			WHERE CAST(LastFinalizedDate AS DATE) BETWEEN @StartDate AND @EndDate
			GROUP BY DistributorID, Distributor;

			
		--Select Format(MAX(LastFinalizedDate),'MMM dd yyyy')  From #Distributors
		 Declare @Month int,@Year int,@LatestDate datetime,@MonthYear nvarchar(30),@CurrentMonthYear nvarchar(30),@ActualUnits decimal(24,2),@AmountTP decimal(24,2),
		 @PMonthYear nvarchar(30),@PActualUnits decimal(24,2),@PAmountTP decimal(24,2),@TargetUnitsasonDate decimal(24,2),@TargetAmountasonDate decimal(24,2)
		 
		 --Select MAX(LastFinalizedDate) from #Distributors

		 Select @LatestDate=MAX(LastFinalizedDate),@Month=Month(MAX(LastFinalizedDate)),
		 @Year=Year(MAX(LastFinalizedDate)) From ss_DistributorMonthWiseFinalizedDate
		 
		 --Select @Param_MonthID
		 --Select @Month
		 if (@Param_MonthID=@Month and Year(@Param_InvoiceDate_To)=@Year)
		 BEGIN
				
				SELECT 
				@MonthYear = CASE WHEN TransType = 2 THEN FORMAT(PFInvoiceDate, 'MMM yy') ELSE @MonthYear END,
				@ActualUnits = CASE WHEN TransType = 2 THEN SUM(PMActualUnits) ELSE @ActualUnits END,
				@AmountTP = CASE WHEN TransType = 2 THEN SUM(PMAmountTP) ELSE @AmountTP END,
				@PMonthYear = CASE WHEN TransType = 1 THEN FORMAT(PFInvoiceDate, 'MMM yy') ELSE @PMonthYear END,
				@PActualUnits = CASE WHEN TransType = 1 THEN SUM(PMActualUnits) ELSE @PActualUnits END,
				@PAmountTP = CASE WHEN TransType = 1 THEN SUM(PMAmountTP) ELSE @PAmountTP END
			FROM tblSalesVsTargetTestPM a
			INNER JOIN #TeamIds b 
				ON a.TeamId = b.TeamID 
				AND a.RegionId = b.RegionID 
				AND a.DistrictId = b.DistrictID 
				AND a.TerritoryId = b.TerritoryID 
				AND a.[3S ProductId] = b.ProducID
			WHERE a.TransType IN (1, 2)
			AND a.SaleType IN (SELECT value FROM dbo.SPLIT(@Param_SalesTypeDescription, ','))
			AND (a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
			GROUP BY TransType, PFInvoiceDate;
			
			SET @CurrentMonthYear = LEFT(@MonthYear, 3) + ' ' + RIGHT('0' + CAST(CAST(RIGHT(@MonthYear, 2) AS INT) + 1 AS VARCHAR), 2);
			--Select @CurrentMonthYear
			SELECT 
			@TargetUnitsasonDate=Sum(TargetUpToToday),
			@TargetAmountasonDate=Sum(AmountTP)
			FROM ss_SalesTargetasonDate a
			INNER JOIN #TeamIds b 
			ON a.TeamId = b.TeamID 
			AND a.RegionId = b.RegionID 
			AND a.DistrictId = b.DistrictID 
			AND a.TerritoryId = b.TerritoryID 
			AND a.[ProductId] = b.ProducID
			WHERE  (a.SalesType IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
			
				

		 END 
		 
		 






	 --Select * from #TeamIds

	 --return

--Select * from #TeamIds






	DECLARE @GetPreviousYearMonth TABLE (
    Year int,
	Month int,
	MonthYear nvarchar(100)
	);

	DECLARE @GetCurrentYearMonth TABLE (
    Year int,
	Month int,
	MonthYear nvarchar(100)
	);


	Insert into @GetCurrentYearMonth(Year,Month,MonthYear)
	SELECT Distinct
		YEAR(_DATE) AS [Year], 
		MONTH(_DATE) AS [Month], 
		FORMAT(_DATE, 'MMM yy') AS [MonthYear]
	FROM dbo.FN_GETDATES_BETWEEN_DATERANGE(@Param_InvoiceDate_From, @Param_InvoiceDate_To)
	--GROUP BY 
	--	YEAR(_DATE),
	--	MONTH(_DATE),
	--	FORMAT(_DATE, 'MMM yy')

		--Select * from #TeamIds
		--return

		SELECT 
		dr.MonthYear,
		ISNULL(a.Units, 0) Units , 
		ISNULL(a.Amount, 0) Amount,
		PUnits=Case When dr.MonthYear=@PMonthYear then @PActualUnits  else ISNULL(a.Units, 0) end , 
		PAmount=Case When dr.MonthYear=@PMonthYear then @PAmountTP else ISNULL(a.Amount, 0) end 
		

	FROM @GetCurrentYearMonth dr
	LEFT JOIN
	(
		Select a.Year,a.MONTH,ISNULL(SUM(a.ActualUnits), 0) Units,
		ISNULL(SUM(a.AmountTP), 0) Amount
		From tblSalesVsTargetTest a  with(nolock) 
		Inner join #TeamIds b on a.TeamId=b.TeamID and a.RegionId=b.RegionID and a.DistrictId=b.DistrictID and a.TerritoryId=b.TerritoryID and a.[3S ProductId]=b.ProducID and a.BrandId=b.BrandID
		WHERE (a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
		and a.FiscalYearFromDate=@Param_InvoiceDate_From and a.FIscalYearToDate=@Param_InvoiceDate_To
		AND a.SaleType IN (SELECT value FROM dbo.SPLIT(@Param_SalesTypeDescription, ','))
		Group By a.Year,a.MONTH
	)a ON a.Year = dr.[Year]
		AND a.MONTH = dr.[Month]
	
	ORDER BY 
		dr.[Year],
		dr.[Month];

--return
	
	--	SELECT 
	--	dr.MonthYear,
	--	ISNULL(SUM(a.ActualUnits), 0) Units , 
	--	ISNULL(SUM(a.AmountTP), 0) Amount,
	--	PUnits=Case When dr.MonthYear=@PMonthYear then @PActualUnits  else ISNULL(SUM(a.ActualUnits), 0) end , 
	--	PAmount=Case When dr.MonthYear=@PMonthYear then @PAmountTP else ISNULL(SUM(a.AmountTP), 0) end 
		

	--FROM @GetCurrentYearMonth dr
	--LEFT JOIN tblSalesVsTargetTest a ON
	--	a.Year = dr.[Year]
	--	AND a.MONTH = dr.[Month]
	--   Inner join #TeamIds b on a.TeamId=b.TeamID and a.RegionId=b.RegionID and a.DistrictId=b.DistrictID and a.TerritoryId=b.TerritoryID and a.[3S ProductId]=b.ProducID and a.BrandId=b.BrandID
		
	--	WHERE 
	--	(@Param_SalesChannel IS NULL OR @Param_SalesChannel = '' OR a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')))
	--	--AND 
	-- --   a.FiscalYearFromDate=@Param_InvoiceDate_From and a.FIscalYearToDate=@Param_InvoiceDate_To
	--GROUP BY 
	--	dr.MonthYear,
	--	dr.[Year],
	--	dr.[Month]
	--ORDER BY 
	--	dr.[Year],
	--	dr.[Month];

	------------

	Insert into @GetPreviousYearMonth(Year,Month,MonthYear)
	SELECT Distinct
			YEAR(_DATE) AS [Year], 
			MONTH(_DATE) AS [Month], 
			FORMAT(_DATE, 'MMM yy') AS [MonthYear]
		FROM dbo.FN_GETDATES_BETWEEN_DATERANGE(DATEADD(year, -1, @Param_InvoiceDate_From), DATEADD(year, -1, @Param_InvoiceDate_To))
		--GROUP BY 
		--	YEAR(_DATE),
		--	MONTH(_DATE),
		--	FORMAT(_DATE, 'MMM yy')



	  SELECT 
    dr.MonthYear,
    ISNULL(a.Units, 0) Units , 
	ISNULL(a.Amount, 0) AS Amount,
	PUnits=Case When dr.MonthYear=@MonthYear then @ActualUnits  else ISNULL(a.Units, 0) end , 
	PAmount=Case When dr.MonthYear=@MonthYear then @AmountTP else ISNULL(a.Amount, 0) end 
		


	--ISNULL(SUM(a.Amount), 0) Amount
	--CASE 
 --       WHEN @Param_IsActualPrice = 1 THEN ISNULL(SUM(a.Amount), 0) 
 --       ELSE ISNULL(SUM(a.AmountTP), 0)
 --   END AS Amount

FROM @GetPreviousYearMonth dr
LEFT JOIN 
(

		Select a.Year,a.MONTH,ISNULL(SUM(a.ActualUnits), 0) Units,
		ISNULL(SUM(a.AmountTP), 0) Amount
		--,
		--PUnits=Case When a.MonthYear=@PMonthYear then @PActualUnits  else ISNULL(SUM(a.ActualUnits), 0) end , 
		--PAmount=Case When a.MonthYear=@PMonthYear then @PAmountTP else ISNULL(SUM(a.AmountTP), 0) end 
		From tblSalesVsTargetTest a with(nolock) Inner join #TeamIds b on a.TeamId=b.TeamID and a.RegionId=b.RegionID and a.DistrictId=b.DistrictID and a.TerritoryId=b.TerritoryID and a.[3S ProductId]=b.ProducID and a.BrandId=b.BrandID
		--WHERE (@Param_SalesChannel IS NULL OR @Param_SalesChannel = '' OR a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')))
		WHERE (a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
		AND a.SaleType IN (SELECT value FROM dbo.SPLIT(@Param_SalesTypeDescription, ','))
		and a.FiscalYearFromDate=DATEADD(year, -1, @Param_InvoiceDate_From) and a.FIscalYearToDate=DATEADD(year, -1, @Param_InvoiceDate_To)
		Group By a.Year,a.MONTH
)a on
--tblSalesVsTargetTest a ON
    a.Year = dr.[Year]
    AND a.MONTH = dr.[Month]
	--Inner join #TeamIds b on a.TeamId=b.TeamID and a.RegionId=b.RegionID and a.DistrictId=b.DistrictID and a.TerritoryId=b.TerritoryID 
	--and a.[3S ProductId]=b.ProducID and a.BrandId=b.BrandID
 --   Where (a.SalesChannel IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
--GROUP BY 
--    dr.MonthYear,
--    dr.[Year],
--    dr.[Month]
ORDER BY 
    dr.[Year],
    dr.[Month];

	---- Current Year Target -----------

IF OBJECT_ID('tempdb..##SalesTaget') is Not Null  
Drop Table #SalesTaget 





Select a.*,b.GroupID into #SalesTaget
From
(
	SELECT 
    a.CompCode, 
    a.FiscalYearFromDate, 
    a.FiscalYearToDate, 
    RegionID=c.RegionID, 
    DistrictID=c.DistrictID, 
    a.TerritoryId, 
    a.TeamId, 
    a.SalesType, 
    a.ProductID, 
    a.Rate, 
    Units = v.TargetQty, 
    v.Month,
    v.Year, -- Add Year column
    p.Product,
    CASE 
        WHEN v.Month = 1 THEN p.JanFlag
        WHEN v.Month = 2 THEN p.FebFlag
        WHEN v.Month = 3 THEN p.MarFlag
        WHEN v.Month = 4 THEN p.AprFlag
        WHEN v.Month = 5 THEN p.MayFlag
        WHEN v.Month = 6 THEN p.JunFlag
        WHEN v.Month = 7 THEN p.JulFlag
        WHEN v.Month = 8 THEN p.AugFlag
        WHEN v.Month = 9 THEN p.SepFlag
        WHEN v.Month = 10 THEN p.OctFlag
        WHEN v.Month = 11 THEN p.NovFlag
        WHEN v.Month = 12 THEN p.DecFlag
        ELSE ''
    END AS MonthFlag,
    CASE 
        WHEN v.Month = 1 THEN p.JanTP
        WHEN v.Month = 2 THEN p.FebTP
        WHEN v.Month = 3 THEN p.MarTP
        WHEN v.Month = 4 THEN p.AprTP
        WHEN v.Month = 5 THEN p.MayTP
        WHEN v.Month = 6 THEN p.JunTP
        WHEN v.Month = 7 THEN p.JulTP
        WHEN v.Month = 8 THEN p.AugTP
        WHEN v.Month = 9 THEN p.SepTP
        WHEN v.Month = 10 THEN p.OctTP
        WHEN v.Month = 11 THEN p.NovTP
        WHEN v.Month = 12 THEN p.DecTP
        ELSE 0
    END AS TPPrice,
    CASE 
        WHEN v.Month = 1 THEN p.JanTP * v.TargetQty
        WHEN v.Month = 2 THEN p.FebTP * v.TargetQty
        WHEN v.Month = 3 THEN p.MarTP * v.TargetQty
        WHEN v.Month = 4 THEN p.AprTP * v.TargetQty
WHEN v.Month = 5 THEN p.MayTP * v.TargetQty
        WHEN v.Month = 6 THEN p.JunTP * v.TargetQty
        WHEN v.Month = 7 THEN p.JulTP * v.TargetQty
        WHEN v.Month = 8 THEN p.AugTP * v.TargetQty
        WHEN v.Month = 9 THEN p.SepTP * v.TargetQty
        WHEN v.Month = 10 THEN p.OctTP * v.TargetQty
        WHEN v.Month = 11 THEN p.NovTP * v.TargetQty
        WHEN v.Month = 12 THEN p.DecTP * v.TargetQty
        ELSE 0
    END AS Value
FROM 
    ss_SalesTarget a with(nolock)
	CROSS APPLY (
    VALUES 
        (1, a.Jan, a.JanValue, CASE WHEN 1 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (2, a.Feb, a.FebValue, CASE WHEN 2 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (3, a.Mar, a.MarValue, CASE WHEN 3 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (4, a.Apr, a.AprValue, CASE WHEN 4 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (5, a.May, a.MayValue, CASE WHEN 5 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (6, a.Jun, a.JunValue, CASE WHEN 6 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (7, a.Jul, a.JulValue, CASE WHEN 7 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (8, a.Aug, a.AugValue, CASE WHEN 8 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (9, a.Sep, a.SepValue, CASE WHEN 9 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (10, a.Oct, a.OctValue, CASE WHEN 10 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (11, a.Nov, a.NovValue, CASE WHEN 11 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END),
        (12, a.Dec, a.DecValue, CASE WHEN 12 >= 7 THEN YEAR(a.FiscalYearFromDate) ELSE YEAR(a.FiscalYearToDate) END)
) v (Month, TargetQty, TargetValue, Year)
INNER JOIN 
    ss_Product_Setup p with(nolock)
ON 
    a.ProductID = p.ProductID 
    AND a.FiscalYearFromDate = p.FiscalYearFromDate
    AND a.FiscalYearToDate = p.FiscalYearToDate

Inner join tblTerritoryMasterNew c on a.TeamID=c.TeamID and a.TerritoryId=c.TerritoryId
WHERE
CAST(a.CompCode AS INT) = 1  and c.active=1
AND a.FiscalYearFromDate = @Param_InvoiceDate_From
AND a.FiscalYearToDate = @Param_InvoiceDate_To
)
a left join SS_Product_Group b with(nolock) on a.ProductID = b.ProductID




----------------

if (isnull(@Param_SalesType,3) not in (2))
BEGIN

			SELECT 
				dr.MonthYear,
				--ISNULL(SUM(a.ActualUnits), 0) Units , ISNULL(SUM(a.Amount), 0)  AS Amount
				--a.[3S ProductId]
				ISNULL(SUM(a.Units), 0) Units , 
				ISNULL(SUM(a.Value), 0)  AS Amount,
				UnitsasonDate=Case When dr.MonthYear=@CurrentMonthYear then @TargetUnitsasonDate  else ISNULL(SUM(a.Units), 0) end , 
				AmountasonDate=Case When dr.MonthYear=@CurrentMonthYear then @TargetAmountasonDate else ISNULL(SUM(a.Value), 0) end 

			FROM 
			(
				SELECT 
					Year AS [Year], 
					Month AS [Month], 
					MonthYear AS [MonthYear]
					From @GetCurrentYearMonth
			) dr

			left JOIN #SalesTaget a ON a.Year = dr.[Year] AND 
			a.MONTH = dr.[Month]
			Inner join #TeamIds b on a.TeamId=b.TeamID and a.RegionId=b.RegionID and a.DistrictId=b.DistrictID and a.TerritoryId=b.TerritoryID 
			and a.ProductID=b.ProducID and a.GroupID=b.BrandID
			AND (a.SalesType IN (SELECT value FROM dbo.split(@Param_SalesChannel, ',')) OR @Param_SalesChannel IS NULL OR @Param_SalesChannel = '')
			--where MonthYear = 'Jul 2023'
			GROUP BY 
				dr.MonthYear,
				dr.[Year],
				dr.[Month]
				--a.[3S ProductId]
			ORDER BY 
				dr.[Year],
				dr.[Month];

END
ELSE
BEGIN
				SELECT 
				dr.MonthYear,
				--ISNULL(SUM(a.ActualUnits), 0) Units , ISNULL(SUM(a.Amount), 0)  AS Amount
				--a.[3S ProductId]
				0 Units , 
				0  AS Amount,
				UnitsasonDate=0 , 
				AmountasonDate=0 

			FROM 
			(
				SELECT 
					Year AS [Year], 
					Month AS [Month], 
					MonthYear AS [MonthYear]
					From @GetCurrentYearMonth
			) dr

END



		Select Product,Jan=a.JanTP,Feb=a.FebTP,Mar=a.MarTP,Apr=a.AprTP,May=a.MayTP,Jun=a.JunTP,Jul=a.JulTP,Aug=a.AugTP,Sep=a.SepTP,Oct=a.OctTP,Nov=a.NovTP,Dec=a.DecTP 
		From SS_Product_Setup a  with(nolock)
		Inner join SS_Employee_Product_AssociationNew b with(nolock) on
		a.ProductID=b.ProductID
		Where a.FiscalYearFromDate=@Param_InvoiceDate_From and a.FiscalYearToDate=@Param_InvoiceDate_To and b.Active=1
		--AND Rtrim(b.TeamId) + Rtrim(b.ProductID) + Rtrim(b.BrandID) in (Select Distinct Rtrim(TeamId) + Rtrim(ProducID) + Rtrim(BrandID) From #TeamIds)
		AND (b.TeamId IN (SELECT value FROM dbo.split(@Param_TeamId, ',')) OR isnull(@Param_TeamId,'') = '')
		AND (b.ProductID IN (SELECT value FROM dbo.split(@Param_ProductId, ',')) OR isnull(@Param_ProductId,'') = '')
		AND (b.BrandID IN (SELECT value FROM dbo.split(@Param_GroupId, ',')) OR isnull(@Param_GroupId,'') = '')

		
		
		
			Declare @Count nvarchar(20)
			-- Count the distributors with records in the specific month and total distributors
			SELECT @Count
				 = '(' + 
						  RTRIM(CAST(SUM(CASE 
										  WHEN MONTH(LastFinalizedDate) = MONTH(@EndDate) THEN 1 
										  ELSE 0 
										END) AS NVARCHAR(10))) + '/' + 
						  RTRIM(CAST(COUNT(DISTINCT DistributorID) AS NVARCHAR(10))) + 
						  ')'
			FROM #Distributors;
			if (@Count is null)
				Set @Count='0/0'
			
			Select [Count]=@Count

			

		DROP TABLE IF EXISTS #Distributors;
		DROP TABLE IF EXISTS #Sales;


END
