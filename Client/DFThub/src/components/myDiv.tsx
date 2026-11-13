import { Button } from "flowbite-react";
import { HiAdjustments, HiOutlineSave } from "react-icons/hi";

const txt_stress = "font-medium text-blue-600 hover:underline dark:text-blue-400";

function MainDiv(props) {
  return <section className="px-4 pb-4 pt-2 sm:px-6"><div className="mx-auto max-w-[1180px]">{props.children}</div></section>;
}

function SubDiv(props) {
  return <section className="workspace-shell"><div className="space-y-5">{props.children}</div></section>;
}

function StressDiv(props) {
  return <section className="workspace-shell"><div className="text-lg text-gray-900 dark:text-gray-200">{props.children}</div></section>;
}

function InfoBar(props) {
  return (
    <div className="inline-flex items-center gap-3 rounded-full border border-blue-100 bg-blue-50 px-4 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200" role="status">
      <span className="font-semibold">{props.title}</span><span>{props.content}</span>
    </div>
  );
}

function InfoCard(props) {
  return (
    <section className="workspace-intro apple-card">
      <div className="p-5 sm:p-7">
        <div className="mb-1 flex items-center gap-2 text-[0.7rem] font-bold uppercase tracking-[0.14em] text-blue-600">DFThub workspace</div>
        <h2 className="mb-2 text-2xl font-semibold tracking-[-0.03em] text-gray-900 dark:text-white sm:text-3xl">{props.title}</h2>
        <div className="max-w-3xl text-[0.95rem] leading-7 text-gray-600 dark:text-gray-300">{props.content}</div>
        {props.children}
        {props.button_show && (
          <div className="mt-5 flex flex-wrap gap-2">
            {props.href_start ? (
              <a className="apple-action" href={props.href_start} onClick={props.onClickStart}>{props.text_start || "Login to Start"}<HiOutlineSave className="ml-2 h-4 w-4" /></a>
            ) : (
              <Button type="submit" gradientDuoTone="greenToBlue" className="apple-press rounded-full" onClick={props.onClickStart}>
                {props.text_start || "Login to Start"}<HiOutlineSave className="ml-2 h-4 w-4" />
              </Button>
            )}
            {props.href_doc ? (
              <a className="apple-action apple-action-secondary" href={props.href_doc}>{props.text_doc || "Read API docs"}<HiAdjustments className="ml-2 h-4 w-4" /></a>
            ) : (
              <Button type="button" color="gray" className="apple-press rounded-full" onClick={props.onClickDoc}>
                {props.text_doc || "Read API docs"}<HiAdjustments className="ml-2 h-4 w-4" />
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function AppCard(props) {
  return <div className="apple-card rounded-2xl p-6">{props.children}</div>;
}

function WorkSpace(props) {
  return (
    <div className="workspace-frame p-2 sm:p-3">
      <div className={`grid min-h-0 gap-3 md:gap-5 ${props.out || ""}`} style={{ minHeight: props.h || undefined }}>
        {props.children}
      </div>
    </div>
  );
}

function WorkCard(props) {
  const { out, h, children, ...rest } = props;
  return <div className={`work-card ${out || ""}`} style={{ minHeight: h || undefined }} {...rest}>{children}</div>;
}

export { MainDiv, SubDiv, StressDiv, InfoBar, InfoCard, AppCard, WorkSpace, WorkCard, txt_stress };
