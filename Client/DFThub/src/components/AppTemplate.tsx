import { HiCheck, HiClock, HiHome, HiInformationCircle, HiOutlineMail, HiX } from "react-icons/hi";

function AppMainInfo(props) {
  const serverState = props.submitNum == null ? "loading" : props.submitNum === -1 ? "offline" : props.submitNum === 0 ? "online" : "active";
  return (
    <div className="hero-surface">
      <div className="relative z-10 max-w-3xl">
        <div className="hero-kicker">Density functional research workspace</div>
        <h1 className="hero-title">Make every calculation <span className="hero-title-accent">count.</span></h1>
        <p className="hero-copy">DFThub helps you parameterize density functionals for the reactions and molecular systems that matter to your research.</p>
        <div className="status-row" aria-label="DFThub status">
          <span className={`status-chip ${serverState === "offline" ? "text-red-600" : "text-emerald-700"}`}>
            {serverState === "offline" ? <HiX className="h-4 w-4" /> : <HiCheck className="h-4 w-4" />}
            {serverState === "loading" ? "Checking API…" : serverState === "offline" ? "API server unavailable" : serverState === "online" ? "API server connected" : `${props.submitNum} jobs submitted`}
          </span>
          <span className="status-chip"><HiClock className="h-4 w-4 text-gray-500" /> Updated {props.updateTime}</span>
          <a className="status-chip transition-colors hover:text-blue-600" href={`mailto:${props.email}`}><HiOutlineMail className="h-4 w-4" /> Contact the team</a>
        </div>
      </div>
    </div>
  );
}

function AppReference(props: { title: string; refs: Record<string, string | null> }) {
  return (
    <div className="reference-card" role="note">
      <div className="flex gap-3">
        <HiInformationCircle className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" />
        <div>
          <p className="font-semibold text-gray-800 dark:text-gray-200">Reference</p>
          <p className="mt-1 leading-6">{props.title}</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            {Object.entries(props.refs).map(([ref, url]) => (
              <li key={ref}>{url ? <a className="text-blue-600 hover:underline" href={url}>{ref}</a> : <span>{ref}</span>}</li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}

function HomeBard(props: any) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4 flex items-center gap-2 text-sm text-gray-500">
      <a className="inline-flex items-center gap-1 hover:text-blue-600" href="/"><HiHome className="h-4 w-4" /> Home</a>
      {props.bread.map((item, idx) => <span key={idx} className="inline-flex items-center gap-2"><span className="text-gray-300">/</span>{item.url ? <a className="hover:text-blue-600" href={item.url}>{item.text}</a> : <span>{item.text}</span>}</span>)}
    </nav>
  );
}

function TopBannerX(infoText) { return <div role="status" className="fixed left-0 top-0 z-50 w-full bg-blue-600 p-3 text-center text-sm text-white">{infoText}</div>; }
function NewsCard(props) { return <article className="apple-card p-5"><a href={props.href}><h3 className="font-semibold text-gray-900 dark:text-white">{props.title}</h3><p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{props.content}</p></a></article>; }

export { AppMainInfo, AppReference, HomeBard, TopBannerX, NewsCard };
