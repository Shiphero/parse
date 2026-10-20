import mark from './assets/brand/parse-mark.png';
import shiphero from './assets/brand/shiphero-logo.svg';

export default function ParseBrand() {
  return <span className="parse-brand" role="img" aria-label="PARSE by ShipHero">
    <img className="parse-mark" src={mark} alt=""/>
    <span className="parse-lockup"><span className="parse-name">PARSE</span><span className="parse-endorsement">by <img src={shiphero} alt=""/></span></span>
  </span>;
}
