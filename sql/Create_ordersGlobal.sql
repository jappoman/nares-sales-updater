USE [GenesiRetail]
GO
/****** Object:  StoredProcedure [dbo].[Create_ordersGlobal]    Script Date: 21/08/2026 12:17:02 ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
-- =============================================
-- Author:		<Author,,Name>
-- Create date: <Create Date,,>
-- Description:	<Description,,>
-- =============================================
ALTER PROCEDURE [dbo].[Create_ordersGlobal]
	
AS
BEGIN
	-- SET NOCOUNT ON added to prevent extra result sets from
	-- interfering with SELECT statements.
	SET NOCOUNT ON;

    /****** Script per comando SelectTopNRows da SSMS  ******/
TRUNCATE TABLE [GenesiRetail].[dbo].ordersGlobal

INSERT [GenesiRetail].[dbo].ordersGlobal
SELECT [idStatoOrdine]
      ,[statoOrdine]
      ,[idTipoOrdine]
      ,[tipoOrdine]
      ,od.[Brand]
      ,[numPreventivo]
      ,[cognomeSelQuotation]
      ,[nomeSelQuotation]
      ,[numOrdine]
      ,[numOrdineRiferimento]
      ,[idSeller]
	  ,nomeCognome= CASE
						WHEN (SELECT [storeManager] from [GenesiRetail].[dbo].[Anagrafica] a WHERE a.[Nome]=[nomeSel] and a.Cognome=[cognomeSel])=1
						then '*(S) ' + [nomeSel]+ ' ' +[cognomeSel]
						ELSE [nomeSel]+ ' ' +[cognomeSel]
					END
      ,[cognomeSel]
      ,[nomeSel]
      ,[idConsumer]
      ,[cognomeCns]
      ,[nomeCns]
      ,[cdStore]
      ,od.[store]
      ,[cdAffiliato]
      ,[dtOrdine]
      ,[dtRichiesta]
      ,[dtMakeDefinitive]
      ,[dtCancel]
      ,od.[CompleteReceivingDate]
      ,[tipoFinanziamento]
      ,[numRate]
      ,[importoDaFinanziare]
      ,[idTipoRiga]
      ,[cdListino]
      ,[tipoRiga]
      ,[isProntaConsegna]
      ,[isOmaggio]
      ,[cdArticolo]
	  ,o.Article
      ,od.[po]
      ,[dtInvoiceB2B]
      ,[cdAlias]
      ,[cdRivestimento]
      ,[cdCategoriaRivestimento]
      ,[Iva]
      ,[aliquotaIva]
      ,[qtaOrdinata]
      ,[totaleSedute]
      ,[totalePesoNetto]
      ,[totalePesoLordo]
      ,[totaleVolume]
      ,[selloutTeorico]
      ,[sconto]
      ,[importoScontatoNetto]
      ,[importoScontato]
      ,[selloutRealeNetto]
      ,[selloutReale]
      ,[consensoMarketing]
      ,[consensoProfiling]
      ,[consensoTeleMarketing]
      ,[consensoThirdParties]
      ,[consensoPrivacy]
      ,[telefonoCasa]
      ,[telefonoMobile]
      ,[telefonoUfficio]
      ,[descrTipoVie]
      ,[nomeVia]
      ,[civicoVia]
      ,[localita]
      ,[cap]
      ,[descrComune]
      ,[Acconto]
      ,[AccontoContabilizzato]
      ,[saldo]
      ,[dataCaricoMagazzino]
      ,[valoreAcquisto]=
						CASE
							WHEN [valoreAcquisto]=0
							THEN ((([selloutRealeNetto])/1.22)*0.5)
							WHEN [valoreAcquisto] is null
							THEN ((([selloutRealeNetto])/1.22)*0.5)
							ELSE [valoreAcquisto]
						END
      ,[cdListinoAcquisto]
      ,[MetodiPagamentoAccontoContabilizzato]
  FROM [GenesiRetail].[dbo].[ordersByDate] od
  inner join [GenesiRetail].[dbo].[orders] o
  ON od.dtOrdine=o.OrderDate
  and od.numOrdine=o.OrderNumber
  and od.cdArticolo=o.ArticleCode
  WHERE tipoRiga not IN ('Piano Protezione Aggiuntiva', 'Piano di protezione') --pezzo extra 06/10/2024
  UNION
  SELECT [idStatoOrdine]='9999'
      ,[OrderStatus]
      ,[idTipoOrdine]='9999'
      ,[OrderType]
      ,[Brand]
      ,[numPreventivo]='9999'
      ,[cognomeSelQuotation]=''
      ,[nomeSelQuotation]=''
      ,[OrderNumber]
      ,[numOrdineRiferimento]='9999'
      ,[idSeller]='9999'
	  ,nomeCognome=CASE
						WHEN (SELECT [storeManager] from [GenesiRetail].[dbo].[Anagrafica] a WHERE a.[Nome]=[SalesConsultantName] and a.Cognome=[SalesConsultandSurname])=1
						then '*(S) ' + [SalesConsultantName]+ ' ' +[SalesConsultandSurname]
						ELSE [SalesConsultantName]+ ' ' +[SalesConsultandSurname]
					END
      ,[SalesConsultandSurname]
      ,[SalesConsultantName]
      ,[ConsumerID]
      ,[ConsumerSurname]
      ,[ConsumerName]
      ,[cdStore]=(select [store_nares] FROM [GenesiRetail].[dbo].[Codifica_Store] cs where cs.[nome_nares] = o1.Store)
      ,[Store]
      ,[cdAffiliato]='9999'
      ,[OrderDate]
      ,[RequestedDeliveryDate]
      ,[MakeDefinitiveDate]
      ,[CancelDate]
      ,[CompleteReceivingDate]
      ,[tipoFinanziamento]=''
      ,[numRate]='9999'
      ,[importoDaFinanziare]='9999'
      ,[idTipoRiga]='9999'
      ,[PricelistCode]
      ,[ArticleType]
      ,[SoldFromWarehouse]
      ,[Gift]
      ,[ArticleCode]
      ,[Article]
      ,[PO]
      ,[dtInvoiceB2B]='01/01/1999'
      ,[AliasCode]
      ,[CoveringCode]
      ,[CoveringCategoryCode]
      ,[TaxDescription]
      ,[TaxRate]
      ,[qtaOrdinata]=0
      ,[Seats]
      ,[totalePesoNetto]=99.99
      ,[GrossWeight]
      ,[Volume]
      ,[GrossPice]
      ,[Discount]
      ,[importoScontatoNetto]=[DiscountAmount]/1.22
      ,[DiscountAmount]
      ,[selloutRealeNetto]=[NetPrice]/1.22
      ,[NetPrice]
      ,[ConsumerMarketingAgreement]
      ,[ConsumerProfilingAgreement]
      ,[ConsumerTeleMarketingAgreement]
      ,[ConsumerThirdPartiesAgreement]
      ,[ConsumerPrivacyAgreement]
      ,[ConsumerTelHome]
      ,[ConsumerTelMobile]
      ,[ConsumerTelOffice]
      ,[ConsumerAddressType]
      ,[ConsumerAddress]
      ,[ConsumerAddressNr]
      ,[ConsumerPlace]
      ,[ConsumerZipCode]
      ,[ConsumerCity]
	  ,TotalDeposits
	  ,TotalDeposits
	  ,Balance
      ,[WharehouseLastLoadDate]
      ,[valoreAcquisto]=-1.00
      ,[cdListinoAcquisto]=''
      ,[MetodiPagamentoAccontoContabilizzato]=''
  FROM [GenesiRetail].[dbo].[orders] o1
  where ArticleType in ('Piano Protezione Aggiuntiva','Piano di protezione')
  TRUNCATE TABLE [GenesiRetail].[dbo].ordersGlobalOrd

  INSERT ordersGlobalOrd
  SELECT [idStatoOrdine]
      ,[statoOrdine]
      ,[tipoOrdine]
      ,[numOrdine]
      ,[cognomeSel]
      ,[nomeSel]
      ,[cdStore]
      ,[store]
      ,[dtOrdine]
      ,[MetodiPagamentoAccontoContabilizzato]
      ,[tipoFinanziamento]
      ,[numRate]
      ,[importoDaFinanziare]
      ,SUM([totaleSedute]) as [totaleSedute]
      ,SUM([selloutTeorico])+(SELECT SUM([selloutTeorico]) FROM [GenesiRetail].[dbo].[ordersGlobal] ogp where ogp.[numOrdine] = og.[numOrdine] and ogp.[dtOrdine] = og.[dtOrdine] and [tipoRiga]in ('Piano Protezione Aggiuntiva','Piano di protezione')) as [selloutTeorico]
      ,SUM([importoScontatoNetto]) as [importoScontatoNetto]
      ,SUM([importoScontato]) as [importoScontato]
      ,SUM([selloutRealeNetto])+(SELECT SUM([selloutRealeNetto]) FROM [GenesiRetail].[dbo].[ordersGlobal] ogp where ogp.[numOrdine] = og.[numOrdine] and ogp.[dtOrdine] = og.[dtOrdine] and [tipoRiga]in ('Piano Protezione Aggiuntiva','Piano di protezione')) as [selloutRealeNetto]
      ,SUM([selloutReale])+(SELECT SUM([selloutReale]) FROM [GenesiRetail].[dbo].[ordersGlobal] ogp where ogp.[numOrdine] = og.[numOrdine] and ogp.[dtOrdine] = og.[dtOrdine] and [tipoRiga]in ('Piano Protezione Aggiuntiva','Piano di protezione')) as [selloutReale]
	  ,SUM([valoreAcquisto])+(SELECT SUM([valoreAcquisto]) FROM [GenesiRetail].[dbo].[ordersGlobal] ogp where ogp.[numOrdine] = og.[numOrdine] and ogp.[dtOrdine] = og.[dtOrdine] and [tipoRiga]in ('Piano Protezione Aggiuntiva','Piano di protezione')) as [valoreAcquisto]
      ,[Acconto]
      ,[AccontoContabilizzato]
      ,[saldo]
  FROM [GenesiRetail].[dbo].[ordersGlobal] og
  where [tipoRiga] not in ('Piano Protezione Aggiuntiva','Piano di protezione')
  group by [idStatoOrdine]
      ,[statoOrdine]
      ,[tipoOrdine]
      ,[numOrdine]
      ,[cognomeSel]
      ,[nomeSel]
      ,[cdStore]
      ,[store]
      ,[dtOrdine]
      ,[MetodiPagamentoAccontoContabilizzato]
      ,[tipoFinanziamento]
      ,[numRate]
      ,[importoDaFinanziare]
      ,[Acconto]
      ,[AccontoContabilizzato]
      ,[saldo]
 
 TRUNCATE TABLE [ordersGlobalDTOrd]

 INSERT [ordersGlobalDTOrd]
  Select [dtOrdine]
      ,[numOrdine]

  FROM [GenesiRetail].[dbo].[ordersGlobal] og
  group by [dtOrdine]
      ,[numOrdine]

truncate table markupGlobal

insert markupGlobal
select o.deliverydate
	,od.cdStore
	,o.store
      ,o.OrderStatus
      ,od.[tipoOrdine]
	  ,od.numOrdine
	,od.selloutRealeNetto
	,o.ArticleType
	,o.Article
	,o.ArticleCode
	,od.valoreAcquisto
	,od.dtOrdine
	,o.Seats 
from orders o
inner join ordersByDate od
  ON od.dtOrdine=o.OrderDate
  and od.numOrdine=o.OrderNumber
  and od.cdArticolo=o.ArticleCode

where deliverydate>='20200101'
  
END
