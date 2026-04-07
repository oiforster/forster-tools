#!/usr/bin/env node
/**
 * gerar_pdf_nfse.js — Gera PDF de NFS-e a partir do XML local
 *
 * Uso:   node gerar_pdf_nfse.js /caminho/para/arquivo.xml
 * Saída: imprime o caminho absoluto do PDF gerado no stdout
 */

'use strict';

const fs   = require('fs');
const path = require('path');
const puppeteer = require('puppeteer-core');
const { XMLParser } = require('fast-xml-parser');

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const MESES = [
  'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
];

// ---------------------------------------------------------------------------
// Helpers de formatação
// ---------------------------------------------------------------------------

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatarCpfCnpj(doc) {
  const d = String(doc ?? '').replace(/\D/g, '');
  if (d.length === 14) return d.replace(/^(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})$/, '$1.$2.$3/$4-$5');
  if (d.length === 11) return d.replace(/^(\d{3})(\d{3})(\d{3})(\d{2})$/, '$1.$2.$3-$4');
  return doc;
}

function formatarCEP(cep) {
  const d = String(cep ?? '').replace(/\D/g, '');
  return d.length === 8 ? d.replace(/^(\d{5})(\d{3})$/, '$1-$2') : cep;
}

function formatarNBS(cNBS) {
  const d = String(cNBS ?? '').replace(/\D/g, '');
  return d.length === 9 ? d.replace(/^(\d{8})(\d)$/, '$1-$2') : cNBS;
}

function formatarCodTrib(cTrib) {
  const d = String(cTrib ?? '').replace(/\D/g, '');
  return d.length === 6 ? d.replace(/^(\d{4})(\d{2})$/, '$1-$2') : cTrib;
}

function formatarDataHora(dhProc) {
  const m = String(dhProc ?? '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!m) return dhProc;
  return `${m[3]}/${m[2]}/${m[1]} às ${m[4]}:${m[5]}`;
}

function formatarCompetencia(dCompet) {
  const m = String(dCompet ?? '').match(/^(\d{4})-(\d{2})/);
  if (!m) return dCompet;
  return `${MESES[parseInt(m[2], 10) - 1]} / ${m[1]}`;
}

function formatarValor(v) {
  return Number(v).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

// ---------------------------------------------------------------------------
// Parser do XML da NFS-e
// ---------------------------------------------------------------------------

function parseNfseXml(xmlStr) {
  const parser = new XMLParser({
    ignoreAttributes: false,
    attributeNamePrefix: '@_',
    parseAttributeValue: false,
    trimValues: true,
    removeNSPrefix: true,
  });
  const doc = parser.parse(xmlStr);

  const nfse    = doc['NFSe'] || doc['nfse'] || doc;
  const infNFSe = nfse['infNFSe']
    || Object.values(nfse).find(v => v && typeof v === 'object' && 'nNFSe' in v)
    || {};

  // toma, serv, trib e dCompet ficam dentro de infNFSe.DPS.infDPS — não no nível de infNFSe
  const infDPS       = (infNFSe['DPS'] || {})['infDPS'] || {};

  const emit         = infNFSe['emit']       || {};
  const ender        = emit['enderNac']      || emit['ender'] || {};

  const toma         = infDPS['toma']        || {};
  const tomaEnd      = toma['end']           || toma['enderNac'] || {};
  const tomaEndNac   = tomaEnd['endNac']     || {};   // CEP fica aqui

  const serv         = infDPS['serv']        || {};
  const cServ        = serv['cServ']         || {};

  // trib está em infDPS.valores.trib, não em infNFSe.trib
  const infDpsValores = infDPS['valores']    || {};
  const trib          = infDpsValores['trib']|| {};
  const tribMun       = trib['tribMun']      || {};

  // vLiq está em infNFSe.valores (campo da NFS-e gerada, fora da DPS)
  const valores       = infNFSe['valores']   || {};

  // Endereço do prestador
  const emitEnderParts = [
    ender['xLgr'] && ender['nro'] ? `${ender['xLgr']}, ${ender['nro']}` : '',
    ender['xCpl']    ? String(ender['xCpl'])    : '',
    ender['xBairro'] ? `Bairro ${ender['xBairro']}` : '',
    ender['xMun'] && ender['UF'] ? `${ender['xMun']}/${ender['UF']}` : '',
    ender['CEP']  ? `CEP ${formatarCEP(String(ender['CEP']))}` : '',
  ].filter(Boolean);

  // Endereço do tomador (CEP fica em end.endNac.CEP, não em end.CEP)
  const tomaEnderParts = [
    tomaEnd['xLgr'] && tomaEnd['nro'] ? `${tomaEnd['xLgr']}, ${tomaEnd['nro']}` : '',
    tomaEnd['xCpl']    ? String(tomaEnd['xCpl'])    : '',
    tomaEnd['xBairro'] ? String(tomaEnd['xBairro']) : '',
    tomaEnd['xMun'] && tomaEnd['UF'] ? `${tomaEnd['xMun']}/${tomaEnd['UF']}` : '',
    tomaEndNac['CEP'] ? `CEP ${formatarCEP(String(tomaEndNac['CEP']))}` : '',
  ].filter(Boolean);

  // Chave de acesso: Id="NFS43101..." — prefixo é "NFS", não "NFSe"
  const rawId       = String(infNFSe['@_Id'] || infNFSe['Id'] || '');
  const chaveAcesso = rawId.replace(/^NFS/i, '');
  const tomaCpfCnpj = String(toma['CNPJ'] || toma['CPF'] || '');

  return {
    nNFSe:            String(infNFSe['nNFSe']  ?? ''),
    dhProc:           String(infNFSe['dhProc'] ?? ''),
    nDFSe:            String(infNFSe['nDFSe']  || infNFSe['nProt'] || ''),
    emitNome:         String(emit['xNome']     ?? ''),
    emitCNPJ:         String(emit['CNPJ']      ?? ''),
    emitEndereco:     emitEnderParts.join(' · '),
    tomaNome:         String(toma['xNome']     ?? ''),
    tomaCpfCnpj,
    tomaEndereco:     tomaEnderParts.join(', '),
    descricaoServico: String(cServ['xDescServ'] ?? ''),
    cNBS:             String(cServ['cNBS']      ?? ''),
    cTribNac:         String(cServ['cTribNac']  ?? ''),
    // tpRetISSQN: 1 = Não Retido, 2 = Retido pelo Tomador, 3 = Retido pelo Intermediário
    issRetido:        String(tribMun['tpRetISSQN']) !== '1',
    xLocEmi:          String(infNFSe['xLocEmi']       ?? ''),
    xLocPrestacao:    String(infNFSe['xLocPrestacao'] ?? ''),
    vLiq:             parseFloat(String(valores['vLiq'] ?? '0')) || 0,
    dCompet:          String(infDPS['dCompet'] ?? ''),   // dCompet fica em infDPS
    chaveAcesso,
    regimeTributario: (() => {
      const op = String(infDPS['opSimpNac'] ?? '');
      if (op === '1') return 'Simples Nacional';
      if (op === '2') return 'Simples Nacional — Excesso de Sublimite';
      if (op === '3') return 'MEI';
      return '';
    })(),
    situacaoTrib: (() => {
      const tp = String(tribMun['tpTrib'] ?? '');
      if (tp === '1') return 'Tributada Integralmente';
      if (tp === '2') return 'Tributada com Dedução';
      if (tp === '3') return 'Imune';
      if (tp === '4') return 'Isenta';
      if (tp === '5') return 'Exportação';
      if (tp === '6') return 'Suspensa por Decisão Judicial';
      if (tp === '7') return 'Suspensa por Processo Administrativo';
      return '';
    })(),
  };
}

// ---------------------------------------------------------------------------
// Geração do HTML
// ---------------------------------------------------------------------------

function gerarHtml(data) {
  const tipoDoc      = data.tomaCpfCnpj.replace(/\D/g, '').length > 11 ? 'CNPJ' : 'CPF';
  const issTag       = data.issRetido
    ? `<span class="meta-tag">ISS retido na fonte</span>`
    : `<span class="meta-tag">ISS não retido na fonte</span>`;
  const situacaoTag  = data.situacaoTrib
    ? `<span class="meta-tag-ok">${esc(data.situacaoTrib)}</span>`
    : '';

  return `<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;700;800;900&family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  .page {
    background: #fff;
    max-width: 680px;
    margin: 0 auto;
    padding: 40px 48px 48px;
    color: #1D1D1F;
    font-family: 'Be Vietnam Pro', sans-serif;
  }
  .header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding-bottom: 24px;
    border-bottom: 0.5px solid #E5E5EA;
    margin-bottom: 28px;
  }
  .logo-area svg { height: 30px; width: auto; }
  .logo-sub { font-family: 'Be Vietnam Pro', sans-serif; font-size: 10px; color: #6E6E73; margin-top: 6px; }
  .nota-info { text-align: right; }
  .nota-num { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 28px; font-weight: 900; color: #1D1D1F; letter-spacing: -0.5px; }
  .nota-sub { font-family: 'Be Vietnam Pro', sans-serif; font-size: 12px; color: #6E6E73; margin-top: 3px; line-height: 1.6; }
  .badge { display: inline-block; font-family: 'Plus Jakarta Sans', sans-serif; font-size: 10px; font-weight: 700; background: #FFF0E8; color: #C2400C; border-radius: 20px; padding: 3px 10px; margin-top: 6px; letter-spacing: 0.3px; }
  .section { margin-bottom: 22px; }
  .section-label { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 10px; font-weight: 800; color: #6E6E73; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }
  .partes-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card { background: #F5F5F7; border-radius: 10px; padding: 14px 18px; }
  .field-name { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px; font-weight: 800; color: #1D1D1F; line-height: 1.4; }
  .field-cnpj { font-family: 'Be Vietnam Pro', sans-serif; font-size: 12px; font-weight: 500; color: #6E6E73; margin-top: 2px; }
  .field-addr { font-family: 'Be Vietnam Pro', sans-serif; font-size: 11.5px; color: #6E6E73; margin-top: 8px; padding-top: 8px; border-top: 0.5px solid #E5E5EA; line-height: 1.6; }
  .servico-card { background: #F5F5F7; border-radius: 10px; padding: 14px 18px; }
  .servico-texto { font-family: 'Be Vietnam Pro', sans-serif; font-size: 13px; color: #3A3A3C; line-height: 1.7; }
  .meta-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .meta-tag { font-family: 'Be Vietnam Pro', sans-serif; font-size: 10.5px; font-weight: 600; color: #6E6E73; background: #EBEBED; border-radius: 6px; padding: 3px 8px; line-height: 1.5; white-space: nowrap; }
  .meta-tag-ok { font-family: 'Be Vietnam Pro', sans-serif; font-size: 10.5px; font-weight: 600; color: #1A7F37; background: #DCFCE7; border-radius: 6px; padding: 3px 8px; line-height: 1.5; white-space: nowrap; }
  .field-regime { font-family: 'Be Vietnam Pro', sans-serif; font-size: 11px; font-weight: 500; color: #3A7D44; background: #DCFCE7; border-radius: 5px; padding: 2px 7px; display: inline-block; margin-top: 5px; }
  .local-row { display: flex; gap: 12px; }
  .local-item { flex: 1; background: #F5F5F7; border-radius: 10px; padding: 12px 16px; }
  .local-label { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 10px; font-weight: 800; color: #6E6E73; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 3px; }
  .local-val { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 13px; font-weight: 700; color: #1D1D1F; }
  .valores-row { display: flex; gap: 12px; margin-top: 28px; }
  .valor-bloco { flex: 2; border: 1px solid #1D1D1F; border-radius: 10px; padding: 16px 20px; }
  .competencia-bloco { flex: 1; border: 1px solid #1D1D1F; border-radius: 10px; padding: 16px 20px; text-align: right; }
  .bloco-label { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 10px; font-weight: 800; color: #6E6E73; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .valor-num { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 28px; font-weight: 900; color: #1D1D1F; letter-spacing: -0.8px; }
  .competencia-val { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 18px; font-weight: 800; color: #1D1D1F; letter-spacing: -0.3px; margin-top: 2px; }
  .footer { margin-top: 28px; padding-top: 20px; border-top: 0.5px solid #E5E5EA; text-align: center; }
  .chave-label { font-family: 'Plus Jakarta Sans', sans-serif; font-size: 10px; font-weight: 800; color: #6E6E73; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
  .chave-val { font-size: 10px; color: #3A3A3C; font-family: 'SF Mono', 'Menlo', monospace; line-height: 1.6; word-break: break-all; }
  .consulta-link { font-family: 'Be Vietnam Pro', sans-serif; font-size: 10px; color: #98989D; margin-top: 6px; }
</style>
</head>
<body>
<div class="page">

  <div class="header">
    <div class="logo-area">
      <svg width="112" height="42" viewBox="0 0 112 42" fill="none" xmlns="http://www.w3.org/2000/svg">
        <g clip-path="url(#clip0_25_20)">
        <path d="M2.78679 39V10.0393H9.5625V14.5746H9.72643C10.4732 13.0082 11.5843 11.7605 13.0596 10.8316C14.5532 9.90268 16.3929 9.43821 18.5786 9.43821C21.7661 9.43821 24.225 10.4036 25.9554 12.3343C27.7039 14.265 28.5782 16.9061 28.5782 20.2575V39H21.7752V21.6236C21.7752 19.5654 21.2925 17.9807 20.3271 16.8696C19.3618 15.7404 17.9138 15.1757 15.983 15.1757C14.6898 15.1757 13.5605 15.4762 12.5952 16.0773C11.6298 16.6602 10.883 17.4798 10.3548 18.5362C9.82661 19.5745 9.5625 20.7948 9.5625 22.1973V39H2.78679ZM44.0585 39.5738C41.2171 39.5738 38.7491 38.9727 36.6544 37.7705C34.5598 36.5502 32.9296 34.8198 31.7639 32.5795C30.6164 30.3209 30.0426 27.6343 30.0426 24.5196V24.465C30.0426 21.3686 30.6255 18.7002 31.7912 16.4598C32.9569 14.2012 34.5871 12.4709 36.6818 11.2687C38.7764 10.0484 41.2262 9.43821 44.0312 9.43821C46.8544 9.43821 49.3134 10.0484 51.408 11.2687C53.5209 12.4709 55.1601 14.1921 56.3259 16.4325C57.4916 18.6729 58.0744 21.3504 58.0744 24.465V24.5196C58.0744 27.6525 57.4916 30.3482 56.3259 32.6068C55.1784 34.8471 53.5573 36.5684 51.4626 37.7705C49.368 38.9727 46.9 39.5738 44.0585 39.5738ZM44.0859 34.0821C45.5248 34.0821 46.7725 33.7087 47.8289 32.962C48.8853 32.2152 49.6959 31.1314 50.2605 29.7107C50.8434 28.2718 51.1348 26.5414 51.1348 24.5196V24.465C51.1348 22.4614 50.8434 20.7493 50.2605 19.3286C49.6776 17.9079 48.8489 16.8241 47.7743 16.0773C46.7178 15.3305 45.4701 14.9571 44.0312 14.9571C42.6287 14.9571 41.3901 15.3305 40.3155 16.0773C39.2591 16.8241 38.4303 17.9079 37.8293 19.3286C37.2464 20.7493 36.955 22.4614 36.955 24.465V24.5196C36.955 26.5414 37.2464 28.2718 37.8293 29.7107C38.4303 31.1314 39.2591 32.2152 40.3155 32.962C41.3901 33.7087 42.6469 34.0821 44.0859 34.0821ZM70.3855 39.5738C67.3801 39.5738 65.1398 38.918 63.6644 37.6066C62.2073 36.2952 61.4787 34.1459 61.4787 31.1587V15.285H57.3805V10.0393H61.4787V2.68982H68.391V10.0393H73.7733V15.285H68.391V30.6123C68.391 32.0148 68.7006 32.9893 69.3199 33.5357C69.9574 34.0639 70.8864 34.328 72.1067 34.328C72.4528 34.328 72.7533 34.3189 73.0083 34.3007C73.2815 34.2643 73.5365 34.237 73.7733 34.2187V39.3279C73.3726 39.3825 72.8808 39.4371 72.298 39.4918C71.7333 39.5464 71.0958 39.5738 70.3855 39.5738ZM87.8329 39.5738C84.9369 39.5738 82.4415 38.9636 80.3469 37.7432C78.2704 36.5229 76.6767 34.7925 75.5656 32.5521C74.4545 30.3118 73.899 27.6616 73.899 24.6016V24.5743C73.899 21.5325 74.4545 18.8823 75.5656 16.6237C76.6949 14.347 78.2704 12.5802 80.2922 11.3234C82.3322 10.0666 84.7365 9.43821 87.5051 9.43821C90.2554 9.43821 92.6324 10.0484 94.636 11.2687C96.6578 12.4709 98.206 14.1648 99.2806 16.3505C100.373 18.5362 100.92 21.0862 100.92 24.0005V26.1862H77.2595V21.6509H97.6686L94.3901 25.8857V23.2629C94.3901 21.3686 94.0986 19.793 93.5158 18.5362C92.9329 17.2795 92.1315 16.3414 91.1115 15.7221C90.0915 15.0846 88.9167 14.7659 87.587 14.7659C86.2392 14.7659 85.037 15.0937 83.9806 15.7495C82.9424 16.387 82.1228 17.3432 81.5217 18.6182C80.9388 19.8932 80.6474 21.4414 80.6474 23.2629V25.8857C80.6474 27.6525 80.9388 29.1643 81.5217 30.4211C82.1228 31.6596 82.9697 32.6159 84.0626 33.2898C85.1554 33.9455 86.4578 34.2734 87.9695 34.2734C89.0988 34.2734 90.0915 34.1004 90.9476 33.7543C91.8036 33.39 92.5049 32.9255 93.0513 32.3609C93.616 31.7962 94.0076 31.1861 94.2261 30.5304L94.2808 30.3391H100.619L100.565 30.6396C100.328 31.7507 99.8908 32.8436 99.2533 33.9182C98.6158 34.9746 97.7597 35.9309 96.6851 36.787C95.6104 37.643 94.3354 38.3261 92.8601 38.8361C91.3847 39.3279 89.709 39.5738 87.8329 39.5738Z" fill="#1D1D1F"/>
        <path d="M103 10C105.734 10 107.266 10 110 10V39H103V10Z" fill="#1D1D1F"/>
        <circle cx="106.5" cy="4.5" r="3.5" fill="#F97316"/>
        </g>
        <defs>
        <clipPath id="clip0_25_20"><rect width="112" height="42" fill="white"/></clipPath>
        </defs>
      </svg>
      <div class="logo-sub">NFS-e · Nota Fiscal de Serviço Eletrônica</div>
    </div>
    <div class="nota-info">
      <div class="nota-num">Nº ${esc(data.nNFSe)}</div>
      <div class="nota-sub">Emissão: ${esc(formatarDataHora(data.dhProc))}<br>Protocolo nº ${esc(data.nDFSe)}</div>
      <span class="badge">NFS-e gerada por notei.app.br</span>
    </div>
  </div>

  <div class="section">
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:6px;">
      <div class="section-label">Prestador de serviços</div>
      <div class="section-label">Tomador de serviços</div>
    </div>
    <div class="partes-grid">
      <div class="card">
        <div class="field-name">${esc(data.emitNome)}</div>
        <div class="field-cnpj">CNPJ ${esc(formatarCpfCnpj(data.emitCNPJ))}</div>
        ${data.regimeTributario ? `<span class="field-regime">${esc(data.regimeTributario)}</span>` : ''}
        <div class="field-addr">${esc(data.emitEndereco)}</div>
      </div>
      <div class="card">
        <div class="field-name">${esc(data.tomaNome)}</div>
        <div class="field-cnpj">${tipoDoc} ${esc(formatarCpfCnpj(data.tomaCpfCnpj))}</div>
        <div class="field-addr">${esc(data.tomaEndereco)}</div>
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-label">Serviço prestado</div>
    <div class="servico-card">
      <div class="servico-texto">${esc(data.descricaoServico)}</div>
      <div class="meta-row">
        <span class="meta-tag">Cod. NBS ${esc(formatarNBS(data.cNBS))}</span>
        <span class="meta-tag">Cod. trib. nac. ${esc(formatarCodTrib(data.cTribNac))}</span>
        ${situacaoTag}
        ${issTag}
      </div>
    </div>
  </div>

  <div class="section">
    <div class="section-label">Local</div>
    <div class="local-row">
      <div class="local-item">
        <div class="local-label">Emissão</div>
        <div class="local-val">${esc(data.xLocEmi)}</div>
      </div>
      <div class="local-item">
        <div class="local-label">Prestação</div>
        <div class="local-val">${esc(data.xLocPrestacao)}</div>
      </div>
    </div>
  </div>

  <div class="valores-row">
    <div class="valor-bloco">
      <div class="bloco-label">Valor total</div>
      <div class="valor-num">${esc(formatarValor(data.vLiq))}</div>
    </div>
    <div class="competencia-bloco">
      <div class="bloco-label">Competência</div>
      <div class="competencia-val">${esc(formatarCompetencia(data.dCompet))}</div>
    </div>
  </div>

  <div class="footer">
    <div class="chave-label">Chave de acesso</div>
    <div class="chave-val">${esc(data.chaveAcesso)}</div>
    <div class="consulta-link">Autenticidade em nfse.gov.br/ConsultaPublica</div>
  </div>

</div>
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Geração do PDF via Puppeteer + Chrome local
// ---------------------------------------------------------------------------

async function gerarPdf(xmlPath) {
  const xmlStr  = fs.readFileSync(xmlPath, 'utf-8');
  const data    = parseNfseXml(xmlStr);
  const html    = gerarHtml(data);

  const outPath = path.join(
    path.dirname(xmlPath),
    path.basename(xmlPath, path.extname(xmlPath)) + '.pdf'
  );

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  try {
    const page = await browser.newPage();
    await page.setContent(html, { waitUntil: 'networkidle0' });
    await page.emulateMediaType('print');
    await page.pdf({
      path: outPath,
      format: 'A4',
      printBackground: true,
      margin: { top: '0', right: '0', bottom: '0', left: '0' },
    });
  } finally {
    await browser.close();
  }

  return outPath;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

const xmlPath = process.argv[2];

if (!xmlPath) {
  process.stderr.write('Uso: node gerar_pdf_nfse.js /caminho/para/arquivo.xml\n');
  process.exit(1);
}

if (!fs.existsSync(xmlPath)) {
  process.stderr.write(`Arquivo não encontrado: ${xmlPath}\n`);
  process.exit(1);
}

gerarPdf(path.resolve(xmlPath))
  .then(outPath => {
    process.stdout.write(outPath + '\n');
  })
  .catch(err => {
    process.stderr.write(`Erro ao gerar PDF: ${err.message}\n`);
    process.exit(1);
  });
