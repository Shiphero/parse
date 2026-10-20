import { ArrowLeft, Download } from 'lucide-react';
import ParseBrand from './ParseBrand';
import mark from './assets/brand/parse-mark.png';
import logo from './assets/brand/parse-logo.svg';

const colors = [
  {name:'ShipHero coral',hex:'#F05D5A',use:'Product mark and brand accents'},
  {name:'ShipHero charcoal',hex:'#242E3A',use:'Wordmark, headings and primary actions'},
  {name:'ShipHero blue',hex:'#4287FF',use:'Focus accents and brand graphics'},
  {name:'Interface blue',hex:'#225BC4',use:'Readable links and selected controls'},
  {name:'Canvas',hex:'#F6F8FB',use:'Quiet background for dense workspaces'},
];
export default function BrandPage() {
  return <div className="brand-page">
    <a className="text-button" href="#guides"><ArrowLeft size={15}/> Back to guides</a>
    <div className="brand-hero"><span className="brand-eyebrow">RETAIL SOLUTIONS</span><ParseBrand/>
      <h1>From retailer requirements<br/>to operational rules.</h1>
      <p><strong>P</strong>olicies <strong>A</strong>nalyzed into <strong>R</strong>ules, <strong>S</strong>tandards &amp; <strong>E</strong>xceptions</p>
    </div>
    <section className="brand-section"><h2>A guide to the identity</h2><p>The coral mark connects PARSE to ShipHero. Its geometric P brings a document and structured rules into one compact symbol. Charcoal typography and blue interface accents keep the workspace clear and focused.</p>
      <div className="brand-asset-grid"><div className="brand-asset"><ParseBrand/><span>Primary lockup · light backgrounds</span></div><div className="brand-asset brand-asset-dark"><img src={mark} alt="Coral PARSE mark on charcoal"/><span>Standalone mark · dark backgrounds</span></div></div>
      <div className="action-row"><a className="secondary" href={logo} download="parse-by-shiphero.svg"><Download size={15}/> Download full logo</a><a className="secondary" href={mark} download="parse-mark.png"><Download size={15}/> Download transparent logo mark</a></div>
    </section>
    <section className="brand-section"><h2>Color palette</h2><div className="brand-colors">{colors.map(color=><div className="brand-color" key={color.hex}><span className="brand-swatch" style={{background:color.hex}}/><strong>{color.name}</strong><code>{color.hex}</code><small>{color.use}</small></div>)}</div></section>
    <section className="brand-section brand-principles"><div><h2>Clear at every size</h2><p>Use the full lockup when space permits. Use the mark alone for app icons. Keep generous clear space; preserve its proportions and transparency.</p></div><div><h2>Built for daily work</h2><p>Use compact tables, plain language and restrained color. Coral identifies the product; approval, warning and error colors keep their operational meanings.</p></div></section>
  </div>;
}
