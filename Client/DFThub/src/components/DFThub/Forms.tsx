/*
 * @Author       : yf_Ming && yf_Ming@csu.edu.cn
 * @Date         : 2023-09-03 23:25:37
 * @LastEditors: yf_Ming@hpc_web yf_Ming@csu.edu.cn
 * @LastEditTime: 2024-01-03 07:53:13
 * @FilePath     : /HXWEB/app/WebHub/WebUI/src/components/DFThub/Forms.tsx
 * Copyright (c) 2023, All Rights Reserved.
 */

import {
  Card,
  TextInput,
  FileInput,
  Button,
  Textarea,
  Progress,
  Dropdown,
} from "flowbite-react";
import axios from "axios";
import { LabelInput } from "../InputTemplate";
import { useEffect, useRef, useState } from "react";
import { HiOutlineChevronDown } from "react-icons/hi";
import { InfoCard } from "../myDiv";
import HistoryTable from "../HistoryTemplate";
import moment from "moment";
import { HomeBard } from "../AppTemplate";

const default_grid = "grid grid-cols-1 md:grid-cols-2 gap-3";

const zeta_options = [
  {
    value: "1",
    name: "1-zeta",
    description: "Minimal valence flexibility for quick workflow checks.",
  },
  {
    value: "2",
    name: "2-zeta",
    description: "Double-zeta valence quality for screening calculations.",
  },
  {
    value: "3",
    name: "3-zeta",
    description: "Triple-zeta valence quality for routine calculations.",
  },
  {
    value: "4",
    name: "4-zeta",
    description: "Quadruple-zeta valence quality for high-accuracy calculations.",
  },
  {
    value: "5",
    name: "5-zeta",
    description: "Quintuple-zeta quality for benchmark and near-basis-limit calculations.",
  },
];

const ecp_options = [
  {
    value: "all-electron",
    name: "All-electron",
    description: "Treat all electrons explicitly without a core potential.",
  },
  {
    value: "ecp",
    name: "ECP",
    description: "Replace inner-core electrons with a matched effective core potential.",
  },
];

const basis_options = [
  {
    zeta: "1",
    ecp: false,
    value: "sto-3g",
    name: "STO-3G",
    description: "For quick workflow checks only.",
  },
  {
    zeta: "2",
    ecp: false,
    value: "6-31g(d)",
    name: "6-31G(d)",
    description: "For light-element organic systems; heavy-element support is limited.",
  },
  {
    zeta: "2",
    ecp: false,
    value: "def2-svp",
    name: "def2-SVP",
    description: "For rapid screening and larger systems.",
  },
  {
    zeta: "2",
    ecp: true,
    value: "lanl2dz-ecp",
    name: "LANL2DZ ECP",
    shortName: "LANL2DZ",
    description: "Matched LANL2DZ basis and ECP for transition metals and heavier elements.",
  },
  {
    zeta: "2",
    ecp: true,
    value: "def2-svp-ecp",
    name: "def2-SVP ECP",
    shortName: "def2-SVP",
    description: "Double-zeta def2 basis with a matched ECP for supported heavy elements (Rb-Rn).",
  },
  {
    zeta: "3",
    ecp: false,
    value: "def2-tzvp",
    name: "def2-TZVP",
    description: "Balances accuracy and cost for routine calculations.",
  },
  {
    zeta: "3",
    ecp: false,
    value: "def2-tzvpd",
    name: "def2-TZVPD",
    description: "Large carbon-rich systems and isomer-energy comparisons requiring diffuse functions at moderate cost.",
  },
  {
    zeta: "3",
    ecp: false,
    value: "cc-pvtz",
    name: "cc-pVTZ",
    description: "Correlation-consistent triple-zeta basis for balanced molecular structures and thermochemistry.",
  },
  {
    zeta: "3",
    ecp: true,
    value: "def2-tzvp-ecp",
    name: "def2-TZVP ECP",
    shortName: "def2-TZVP",
    description: "Triple-zeta def2 basis with a matched ECP for supported heavy elements (Rb-Rn).",
  },
  {
    zeta: "4",
    ecp: false,
    value: "def2-qzvp",
    name: "def2-QZVP",
    description: "Current default; high accuracy with the highest computational cost.",
  },
  {
    zeta: "4",
    ecp: false,
    value: "aug-pc-3",
    name: "aug-pc-3",
    description: "Molecular electric-response properties, including dipoles, polarizabilities, and higher-order responses.",
  },
  {
    zeta: "4",
    ecp: false,
    value: "aug-cc-pvqz",
    name: "aug-cc-pVQZ",
    description: "Molecular response to external electric fields and other diffuse-property calculations.",
  },
  {
    zeta: "4",
    ecp: false,
    value: "cc-pvqz",
    name: "cc-pVQZ",
    description: "Higher-accuracy correlation-consistent basis for reaction energies and benchmark calculations.",
  },
  {
    zeta: "4",
    ecp: false,
    value: "def2-qzvpp",
    name: "def2-QZVPP",
    description: "Reaction barriers, organometallic chemistry, and transition-metal thermochemistry.",
  },
  {
    zeta: "4",
    ecp: false,
    value: "def2-qzvppd",
    name: "def2-QZVPPD",
    description: "For anions, weak interactions, and systems requiring diffuse functions.",
  },
  {
    zeta: "4",
    ecp: true,
    value: "def2-qzvp-ecp",
    name: "def2-QZVP ECP",
    shortName: "def2-QZVP",
    description: "Quadruple-zeta def2 basis with a matched ECP for supported heavy elements (Rb-Rn).",
  },
  {
    zeta: "4",
    ecp: true,
    value: "def2-qzvppd-ecp",
    name: "def2-QZVPPD ECP",
    shortName: "def2-QZVPPD",
    description: "Diffuse quadruple-zeta def2 basis with a matched ECP for supported heavy elements (Rb-Rn).",
  },
  {
    zeta: "4",
    ecp: true,
    value: "aug-cc-pwcvqz-pp",
    name: "aug-cc-pwCVQZ-PP",
    shortName: "aug-cc-pwCVQZ",
    description: "Ionization energies and spin-state energetics of heavier transition metals using a matched pseudopotential.",
  },
  {
    zeta: "5",
    ecp: false,
    value: "aug-pc-4",
    name: "aug-pc-4",
    description: "High-accuracy electron affinities and ionization potentials for atoms and small molecules.",
  },
  {
    zeta: "5",
    ecp: false,
    value: "aug-cc-pcv5z",
    name: "aug-cc-pCV5Z",
    description: "High-accuracy atomic energies where core-valence correlation is important.",
  },
  {
    zeta: "5",
    ecp: false,
    value: "d-aug-cc-pv5z",
    name: "d-aug-cc-pV5Z",
    description: "Noble-gas systems and long-range weak interactions requiring extremely diffuse functions.",
  },
];

type CascadingOption = {
  value: string;
  name: string;
  shortName?: string;
  description: string;
};

function CascadingDropdown(props: {
  label: string;
  testId: string;
  value: string;
  options: CascadingOption[];
  onSelect: (value: string) => void;
}) {
  const selected = props.options.find((option) => option.value === props.value);
  const selectedName = selected?.shortName ?? selected?.name ?? props.value;
  const selectedTextSize = selectedName.length > 12 ? "text-[9px]" : "text-[10px]";

  return (
    <div className="min-w-0">
      <div className="mb-1 truncate text-xs font-medium text-gray-700 dark:text-gray-300">
        {props.label}
      </div>
      <Dropdown
        label={selectedName}
        arrowIcon={false}
        placement="bottom-start"
        className="max-w-[calc(100vw-1rem)]"
        renderTrigger={() => (
          <button
            type="button"
            aria-label={`Choose ${props.label}`}
            data-testid={`${props.testId}-trigger`}
            className="apple-press flex h-10 w-full min-w-0 items-center justify-between gap-0 overflow-hidden rounded-xl border border-gray-200 bg-white/80 px-2 text-left text-gray-900 shadow-sm transition-transform hover:bg-white focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 sm:gap-1 sm:px-2 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600"
          >
            <span className={`min-w-0 truncate ${selectedTextSize}`}>{selectedName}</span>
            <HiOutlineChevronDown className="h-3 w-3 shrink-0 sm:h-4 sm:w-4" aria-hidden="true" />
          </button>
        )}
      >
        {props.options.map((option) => (
          <Dropdown.Item
            key={option.value}
            className="items-start rounded-xl px-3 py-2 transition-colors duration-150 hover:bg-blue-50 dark:hover:bg-gray-700"
            data-testid={`${props.testId}-option-${option.value}`}
            onClick={() => props.onSelect(option.value)}
          >
            <span className="block max-w-[min(22rem,calc(100vw-2rem))] text-left">
              <span className="block break-words font-medium">{option.name}</span>
              <span className="mt-0.5 block whitespace-normal text-xs leading-4 text-gray-500 dark:text-gray-400">
                {option.description}
              </span>
            </span>
          </Dropdown.Item>
        ))}
      </Dropdown>
    </div>
  );
}

function genWorkId() {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "";
  for (let i = 0; i < 6; i++) s += chars[Math.floor(Math.random() * chars.length)];
  return "dft_" + s;
}

async function downloadAuthenticatedFile(url: string) {
  try {
    const response = await axios.get(url, { responseType: "blob" });
    const disposition = response.headers["content-disposition"] ?? "";
    const filenameMatch = disposition.match(/filename="?([^";]+)"?/i);
    const filename = filenameMatch?.[1] ?? "download";
    const blobUrl = URL.createObjectURL(response.data);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    console.error("Download failed", error);
    alert("Download failed. Please try again.");
  }
}

function FormWorkNew(props) {
  const [workId, setWorkId] = useState(genWorkId);
  const user = props.user;
  const [initWeight, setInitWeight] = useState(0.02);
  const [zeta, setZeta] = useState("4");
  const [useEcp, setUseEcp] = useState(false);
  const [basis, setBasis] = useState("def2-qzvp");
  const Data = {
    gifFile: useRef<HTMLInputElement>(null),
    refFile: useRef<HTMLInputElement>(null),
    initWeight: useRef<HTMLInputElement>(null),
    userEmail: useRef<HTMLInputElement>(null),
    reMark: useRef<HTMLInputElement>(null),
  };
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [progressColor, setProgressColor] = useState("");
  const availableBasis = basis_options.filter(
    (option) => option.zeta === zeta && option.ecp === useEcp
  );
  const ecpAvailable = basis_options.some(
    (option) => option.zeta === zeta && option.ecp
  );

  useEffect(() => {
    if (
      availableBasis.length > 0 &&
      !availableBasis.some((option) => option.value === basis)
    ) {
      setBasis(availableBasis[0].value);
    }
  }, [basis, zeta, useEcp]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setProgress(0);
    setProgressText("");
    const formData1 = new FormData();
    const work_dir = `Work/${user}/${workId}/`;
    const Weight_csv = new File(
      [
        "Database,Description,Type,Source,Number,Inverse Weight \n" +
          Data.gifFile.current.files[0].name.slice(0, -4) +
          ",,,uploaded,," +
          Data.initWeight.current.value,
      ],
      "init_weight.csv"
    );
    // console.log(Weight_csv)
    formData1.append("folder_dir", work_dir + "upload");
    formData1.append("files", Data.gifFile.current.files[0]);
    formData1.append("files", Data.refFile.current.files[0]);
    formData1.append("files", Weight_csv);
    axios.put("/api_dft/upload", formData1).then(
      (res) => {
        setProgress(70);
        setProgressText("Start Work...");
        // const weight = Number(Data.initWeight.current.value) / 1000
        const Data2 = {
          mode: "new",
          work_dir: work_dir,
          weightFile: "weight_0",
          basis: basis,
          email: Data.userEmail.current.value,
          reMark: Data.reMark.current.value,
        };
        axios.post("/api_dft/submit", Data2).then(
          (res) => {
            if (res.data.result === "error") {
              setProgressColor("red");
              setProgressText(res.data.msg || "Work Start Error");
              return;
            }
            props.setWork(workId);
            setProgress(100);
            setProgressColor("green");
            setProgressText("Submit Finish");
          },
          (error) => {
            setProgressColor("red");
            setProgressText("Work Start Error");
          }
        );
      },
      (error) => {
        setProgressColor("red");
        setProgressText("Upload Error");
      }
    );
    setProgress(30);
    setProgressColor("indigo");
    setProgressText("Upload Work...");
  }

  return (
    <form id="form_jobnew" onSubmit={(e) => handleSubmit(e)}>
      <InfoCard
        title={props.title}
        content=""
        button_show
        href_start={null}
        text_start={"Submit"}
        href_doc={"/api_dft/download/Work/template"}
        text_doc={"Template"}
      >
        <div
          className="grid grid-cols-1 justify-center grow"
          style={{ minHeight: "clamp(24rem, 60vh, 44rem)" }}
        >
          <LabelInput
            id="1. work ID"
            type="text"
            help={"You can rename your work ID here"}
            required={false}
            func={TextInput}
            placeholder={"dft_xxxxxx"}
            value={workId}
            onChange={(e) => {
              setWorkId(e.target.value);
            }}
          />
          <LabelInput
            id="2. YourDatabaseName.tgz"
            type=".tgz"
            help={
              <p className="text-left">
                <b>Upload file: geometry files compressed as *.tgz file.</b>
                <li>
                  The name of each input file should be different with each
                  other.
                </li>
                <li>
                  The format of the input files should be xyz files with charge
                  and spin multiplicity of the molecule provided in the second
                  line.
                </li>
                <li>
                  Each input file contains only one molecule or transition state
                  system.
                </li>{" "}
              </p>
            }
            required={true}
            reference={Data.gifFile}
            func={FileInput}
            placeholder={null}
          />
          <LabelInput
            id="3. YourDatabaseName.ref"
            type=".ref"
            help={
              <p className="max-w-[calc(100vw-3rem)] text-left sm:w-96">
                <b>Upload file: reference energy as *_ref file.</b>
                <li>
                  The format of the reference file can be found in the template.
                </li>
                <li>
                  The reference file should contain the chemical reaction energy
                  calculation formulas and the corresponding reference energies
                  which were obtained from experimental data or high precision
                  calculation results (for example, CCSD(T)/CBS level
                  calculation).{" "}
                </li>
                <li>
                  The names of molecules in the reference file should be the
                  same as the names of the corresponding xyz files.{" "}
                </li>{" "}
              </p>
            }
            required={true}
            reference={Data.refFile}
            func={FileInput}
            placeholder={null}
          />
          <LabelInput
            id="4. initial inverse weight"
            type="number"
            help={
              "Set an init weight (0.001~10) for your giFile set, default 0.02"
            }
            required={true}
            reference={Data.initWeight}
            func={TextInput}
            value={initWeight}
            onChange={(e) => {
              e.target.value < 0.001
                ? setInitWeight(0.001)
                : e.target.value > 10
                  ? setInitWeight(10)
                  : setInitWeight(e.target.value);
            }}
          />
          <LabelInput
            id="5. Email"
            type="email"
            help={"Your email to get result message"}
            required={true}
            reference={Data.userEmail}
            func={TextInput}
            placeholder={"user@example.com"}
            defaultValue={props.userEmail || ""}
          />
          <fieldset>
            <legend className="mb-2 w-full text-center text-base font-medium text-gray-900 dark:text-white">
              6. Basis
            </legend>
            <div className="grid grid-cols-[minmax(0,0.7fr)_minmax(0,1fr)_minmax(0,1.3fr)] gap-1.5 sm:gap-3">
              <CascadingDropdown
                label="N-zeta"
                testId="basis-zeta"
                value={zeta}
                options={zeta_options}
                onSelect={(value) => {
                  setZeta(value);
                  if (
                    !basis_options.some(
                      (option) => option.zeta === value && option.ecp
                    )
                  ) {
                    setUseEcp(false);
                  }
                }}
              />
              <CascadingDropdown
                label="ECP"
                testId="basis-ecp"
                value={useEcp ? "ecp" : "all-electron"}
                options={ecpAvailable ? ecp_options : ecp_options.slice(0, 1)}
                onSelect={(value) => setUseEcp(value === "ecp")}
              />
              <CascadingDropdown
                label="Final basis"
                testId="basis-final"
                value={basis}
                options={availableBasis}
                onSelect={setBasis}
              />
            </div>
          </fieldset>
          <LabelInput
            id="7. Remarks"
            type="text"
            help={
              <>
                Your Remark for this task. <br />
                While you are worried that we cannot understand or other
                situations .
              </>
            }
            required={false}
            reference={Data.reMark}
            func={Textarea}
            placeholder={
              "While you are worried that we cannot understand or other situations ."
            }
          />
          <Progress
            labelProgress
            labelText
            size="lg"
            textLabel={progressText}
            progress={progress}
            color={progressColor}
          />
        </div>
      </InfoCard>
    </form>
  );
}

async function getWorklist(setList, file_dir, file_type, file_is) {
  await axios
    .post("/api_dft/file_list", {
      // TODO:更新了接口名称
      file_dir: "Work/" + file_dir,
      file_filter: file_type,
      file_or_folder: file_is,
    })
    .then((response) => {
      const res_list = response.data.result;
      let req_list = [];
      // console.log("getWorklist", res_list)
      res_list.map((item, idx) => {
        const new_data = {
          key: idx,
          name: item.name,
          submit_time: moment(parseInt(item.time_modify) * 1000)
            .subtract(8, "hours")
            .format("YYYY-MM-DD"),
          status: item.status,
          total_mue: item.total_mue.split(":")[1],
        };
        req_list.push(new_data);
      });
      setList(req_list.reverse());
      // console.log("setWorkList", req_list)
    })
    .catch((error) => {
      setList([]);
      console.log("get list failure", error);
    });
}

function FormWorkChoose(props) {
  const [workList, setWorkList] = useState([]);
  const shouldAutoload = props.autoload !== false || Boolean(props.handle);

  useEffect(() => {
    if (!props.file_dir || !shouldAutoload) {
      setWorkList([]);
      return;
    }

    getWorklist(setWorkList, props.file_dir, "*", props.file_is);
  }, [props.file_dir, props.file_is, props.handle, shouldAutoload]);

  useEffect(() => {
    if (props.setWeightNum) {
      props.setWeightNum(workList.length);
    }
  }, [props.setWeightNum, workList.length]);

  // console.log("FormWorkChoose Load", workList)
  function handleWorkList(file_type) {
    getWorklist(setWorkList, props.file_dir, file_type, props.file_is);
  }
  const [fileType, setFileType] = useState("");
  const onClickFileType = (e) => {
    fileType ? handleWorkList("*" + fileType + "*") : handleWorkList("*");
  };
  const privateDownloadUrl =
    "/api_dft/download/Work/" + props.file_dir + props.downdir;
  const handlePrivateDownload = () => {
    if (!props.downdir) {
      alert("Please select a work first.");
      return;
    }
    void downloadAuthenticatedFile(privateDownloadUrl);
  };
  return (
    <div className="w-full" id="form_submit">
      <InfoCard
        {...props}
        title={props.title}
        content={HomeBard(props)}
        href_doc={props.href_doc ?? null}
        onClickDoc={props.onClickDoc ?? handlePrivateDownload}
      >
        <div className="grid grid-cols-3 gap-3 mb-2">
          <div className="col-span-2">
            <TextInput
              type="text"
              required={false}
              onChange={(e) => {
                setFileType(e.target.value);
              }}
            />
          </div>
          <Button color="info" onClick={onClickFileType}>
            Search
          </Button>
        </div>
        <div
          className="overflow-auto rounded-lg
        outline outline-gray-200 dark:outline-gray-700 "
          style={{ maxHeight: props.h, minHeight: "18rem" }}
        >
          <HistoryTable
            work_list={workList}
            head_list={props.columns}
            handleFresh={onClickFileType}
            {...props}
          />
        </div>
        {props.children}
      </InfoCard>
    </div>
  );
}

function FormWorkResult(props) {
  const base_api = props.user && props.work && props.weight
    ? `/api_dft/download/Work/${props.user}/${props.work}/output/${props.weight}/`
    : "";
  const [mue, setMue] = useState("");
  const [parameters, setParameters] = useState("");
  const [process, setProcess] = useState("");
  const [showValue, setShowValue] = useState("");
  const [barChoose, setBarchoose] = useState(0);
  const fetchData = dataFetchGetHandle(base_api);
  useEffect(() => {
    if (!props.user || !props.work || !props.weight) {
      setMue("");
      setParameters("");
      setProcess("");
      setShowValue("");
      setBarchoose(0);
      return;
    }

    const fetchDataList = ["Mue", "Parameters", "process.log"];
    Promise.all(fetchDataList.map(fetchData)).then(
      ([mue, parameters, process]) => {
        setMue(mue);
        setParameters(parameters);
        setProcess(process);
        setShowValue(mue || "");
      }
    );
  }, [base_api, props.user, props.work, props.weight]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      <div className="col-span-1 lg:col-span-2">
        <FormWorkChoose
          title={props.title}
          handle={props.weight}
          h="53vh"
          button_show={true}
          file_dir={props.user + "/" + props.work + "/output/"}
          file_is="folder"
          setHandle={props.setHandle}
          bread={[
            { text: props.work, url: "#Start" },
            { text: "weight", url: null },
          ]}
          columns={["name", "Total_MUE", "submit_time", "Status"]}
          {...props}
        />
      </div>
      <Card>
        <div>
          <Button.Group>
            <Button
              color={barChoose == 0 ? "info" : "gray"}
              onClick={(e) => {
                setBarchoose(0), setShowValue(mue);
              }}
            >
              mue
            </Button>
            <Button
              color={barChoose == 1 ? "info" : "gray"}
              onClick={(e) => {
                setBarchoose(1), setShowValue(parameters);
              }}
            >
              parameters
            </Button>
            <Button
              color={barChoose == 2 ? "info" : "gray"}
              onClick={(e) => {
                setBarchoose(2), setShowValue(process);
              }}
            >
              process
            </Button>
          </Button.Group>
        </div>
        <div
          className="flex rounded-md justify-center overflow-scroll
            bg-gray-100 border-2 border-gray-200 dark:border-gray-700 dark:bg-gray-800 text-sm"
          style={{ minHeight: "24rem", maxHeight: "44rem" }}
        >
          <Csv2Table csv={showValue} />
        </div>
      </Card>
    </div>
  );
}

function dataFetchGetHandle(base_api: string) {
  // 用以返回一个文本数据获取句柄，如果得到的不是文本值，则返回空
  return async (api) => {
    try {
      const res = await axios.get(base_api + api);
      return typeof res.data === "string" ? res.data : "";
    } catch {
      return "";
    }
  };
}

function Csv2Table(props: any) {
  // console.log("Csv2Table", props.csv);
  return (
    <table className="font-mono">
      <caption className="caption-top">{props.csv.split("\n")[0]}</caption>
      <tbody className="">
        {props.csv
          .split("\n")
          .slice(1)
          .map((item: any, index: any) => {
            return (
              <tr key={index}>
                {item.split("\t").map((item: any, index: any) => {
                  return <td key={index}>{item}</td>;
                })}
              </tr>
            );
          })}
      </tbody>
    </table>
  );
}

function FormWeightOptim(props) {
  const base_api = props.user && props.work && props.weight
    ? `/api_dft/download/Work/${props.user}/${props.work}/output/${props.weight}/`
    : "";
  const [weightCsv, setWeightCsv] = useState("");
  const fetchData = dataFetchGetHandle(base_api);
  useEffect(() => {
    if (!props.user || !props.work || !props.weight) {
      setWeightCsv("");
      return;
    }

    fetchData("weight.csv").then((res) => {
      setWeightCsv(res);
    });
  }, [base_api, props.user, props.work, props.weight]);
  const [newWeightCsv, setNewWeightCsv] = useState("");
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState("");
  const [progressColor, setProgressColor] = useState("");
  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setProgress(0);
    setProgressText("");
    if (newWeightCsv == "") {
      setProgress(30);
      setProgressColor("red");
      setProgressText("Weight not Change");
      console.log("error");
    } else {
      const formData1 = new FormData();
      const weight_folder = props.weight.split("_")[0] + "_" + props.weightNum;
      const work_dir = `Work/${props.user}/${props.work}`;
      const Weight_csv = new File([newWeightCsv], "weight.csv");
      props.setWeight(weight_folder);
      console.log(weight_folder);
      formData1.append("folder_dir", work_dir + `/output/${weight_folder}`);
      formData1.append("files", Weight_csv);
      axios.put("/api_dft/upload", formData1).then(
        (res) => {
          setProgress(70);
          setProgressText("Start Work...");
          // const weight = Number(Data.initWeight.current.value) / 1000
          const Data2 = {
            mode: "optim",
            work_dir: work_dir,
            weightFile: weight_folder,
          };
          setNewWeightCsv("");
          axios.post("/api_dft/submit", Data2).then(
            (res) => {
              if (res.data.result === "error") {
                setProgressColor("red");
                setProgressText(res.data.msg || "Work Start Error");
                return;
              }
              setProgress(100);
              setProgressColor("green");
              setProgressText("Submit Finish");
            },
            (error) => {
              setProgressColor("red");
              setProgressText("Work Start Error");
            }
          );
        },
        (error) => {
          setProgressColor("red");
          setProgressText("Upload Error");
        }
      );
      setProgress(30);
      setProgressColor("indigo");
      setProgressText("Upload Work...");
    }
  }

  function handleReset(e) {
    e.preventDefault();
    setProgress(50);
    setProgressColor("gray");
    setProgressText("");
    setNewWeightCsv(weightCsv);
  }
  return (
    <form
      onSubmit={(e) => handleSubmit(e)}
      onResetCapture={(e) => handleReset(e)}
    >
      <InfoCard
        button_show
        props={props}
        title={props.title}
        content={props.content}
        text_start={props.text_start}
        text_doc={props.text_doc}
        href_start={props.href_start}
        href_doc={props.href_doc}
      >
        <div className="">
          <div
            className="flex overflow-auto outline rounded-md justify-center
            bg-gray-100 border-2 border-gray-200 dark:border-gray-700 dark:bg-gray-800 "
            style={{ minHeight: "18rem", maxHeight: "42rem" }}
          >
            {weightCsv ? (
              <Csv2Table2
                csv={weightCsv}
                setNewWeightCsv={setNewWeightCsv}
                {...props}
              />
            ) : (
              ""
            )}
          </div>
        </div>
        <Progress
          labelProgress
          labelText
          size="lg"
          textLabel={progressText}
          progress={progress}
          color={progressColor}
        />
        {/* <Button gradientDuoTone="cyanToBlue">Get results</Button> */}
      </InfoCard>
    </form>
  );
}

type SinglePointTargetRow = {
  index: number;
  system: string;
  reference: number;
  calculated: number;
  unbiasedError: number;
};

type SinglePointSummaryRow = {
  name: string;
  mue: number;
};

type SinglePointResultsPayload = {
  targetDatabaseTitle: string;
  targetRows: SinglePointTargetRow[];
  targetMue: number;
  summaryTitle: string;
  summaryRows: SinglePointSummaryRow[];
  userDatasetTitle?: string;
  userTargetRows?: SinglePointTargetRow[];
  userTargetMue?: number;
};

type OptimizerResultEntry = {
  RMSE: number;
  MUE?: number;
  res?: number[];
};

type OptimizerResultsPayload = Record<string, OptimizerResultEntry>;

type ResultsData =
  | { kind: "legacy"; data: SinglePointResultsPayload }
  | { kind: "optimizer"; data: OptimizerResultsPayload };

function FormSinglePointResults(props) {
  const base_api = props.user && props.work && props.weight
    ? `/api_dft/download/Work/${props.user}/${props.work}/output/${props.weight}/`
    : "";
  const [results, setResults] = useState<ResultsData | null>(null);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    if (!props.user || !props.work || !props.weight) {
      setResults(null);
      setLoadError("");
      return;
    }

    axios
      .get(base_api + "SinglePointResults.json")
      .then((res) => {
        const payload =
          typeof res.data === "string" ? JSON.parse(res.data) : res.data;
        setResults({ kind: "legacy", data: payload });
        setLoadError("");
      })
      .catch(() => {
        setResults(null);
        setLoadError(
          "Single point energy results not available yet. Click \"Calculate Single Point Energy\" in section ③ to start."
        );
      });
  }, [base_api, props.user, props.work, props.weight]);

  return (
    <InfoCard
      button_show
      title={props.title}
      content={props.content}
      text_start={props.text_start}
      text_doc={props.text_doc}
      href_start={props.href_start}
      href_doc={props.href_doc}
    >
      <div
        className="overflow-auto rounded-md border-2 border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800"
        style={{ minHeight: "18rem", maxHeight: "42rem" }}
      >
        {results ? (
          results.kind === "legacy" ? (
            <SinglePointResultsView results={results.data} />
          ) : (
            <OptimizerResultsView results={results.data} />
          )
        ) : (
          <div className="py-16 text-center text-sm text-gray-500 dark:text-gray-400">
            {loadError || "Loading result table..."}
          </div>
        )}
      </div>
    </InfoCard>
  );
}

function SinglePointResultsView(props: { results: SinglePointResultsPayload }) {
  const { results } = props;
  return (
    <div className="space-y-4 text-gray-700 dark:text-gray-200">
      {results.userTargetRows && results.userTargetRows.length > 0 && (
        <SinglePointResultSection
          title={results.userDatasetTitle ?? "Results Of Target Database"}
          headers={["Index", "Reference", "Calculated", "Unbiased Error"]}
          rows={results.userTargetRows.map((row) => [
            row.index,
            formatResultNumber(row.reference),
            formatResultNumber(row.calculated),
            formatResultNumber(row.unbiasedError),
          ])}
          footerLabel="Mean Unbiased Error (MUE):"
          footerValue={formatResultNumber(results.userTargetMue ?? 0)}
        />
      )}
      <SinglePointResultSection
        title="Results Of AME418"
        headers={["Sub-database", "MUE"]}
        rows={results.summaryRows.map((row) => [
          row.name,
          formatResultNumber(row.mue),
        ])}
      />
    </div>
  );
}

function OptimizerResultsView(props: { results: OptimizerResultsPayload }) {
  const { results } = props;

  const params = Object.entries(results)
    .filter(([, v]) => v.MUE === undefined)
    .map(([name, v]) => ({ name, rmse: v.RMSE }));

  const databases = Object.entries(results)
    .filter(([, v]) => v.MUE !== undefined)
    .map(([name, v]) => ({
      name: name.replace(/_ref$/, ""),
      mue: v.MUE!,
      rmse: v.RMSE,
    }));

  return (
    <div className="space-y-4 text-gray-700 dark:text-gray-200">
      {params.length > 0 && (
        <SinglePointResultSection
          title="Optimized Parameters (RMSE)"
          headers={["Parameter", "RMSE"]}
          rows={params.map((p) => [p.name, formatResultNumber(p.rmse)])}
        />
      )}
      <SinglePointResultSection
        title="Database Results"
        headers={["Database", "MUE", "RMSE"]}
        rows={databases.map((d) => [
          d.name,
          formatResultNumber(d.mue),
          formatResultNumber(d.rmse),
        ])}
      />
    </div>
  );
}

function SinglePointResultSection(props: {
  title: string;
  headers: Array<string>;
  rows: Array<Array<string | number>>;
  footerLabel?: string;
  footerValue?: string;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-gray-300 dark:border-gray-600">
      <div className="border-b border-gray-300 bg-gray-50 px-4 py-2 text-center text-sm font-semibold dark:border-gray-600 dark:bg-gray-700">
        {props.title}
      </div>
      <table className="w-full table-auto text-center text-sm">
        <thead className="bg-gray-100 text-xs font-semibold uppercase tracking-wide dark:bg-gray-700">
          <tr>
            {props.headers.map((header) => (
              <th key={header} className="px-3 py-2">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.rows.map((row, rowIndex) => (
            <tr
              key={`${props.title}_${rowIndex}`}
              className="border-t border-gray-200 dark:border-gray-700"
            >
              {row.map((value, valueIndex) => (
                <td key={valueIndex} className="px-3 py-1.5">
                  {value}
                </td>
              ))}
            </tr>
          ))}
          {props.footerLabel ? (
            <tr className="border-t border-gray-300 bg-gray-50 font-semibold dark:border-gray-600 dark:bg-gray-700">
              <td
                colSpan={props.headers.length - 1}
                className="px-3 py-2 text-right"
              >
                {props.footerLabel}
              </td>
              <td className="px-3 py-2">{props.footerValue}</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function formatResultNumber(value: number) {
  return value.toFixed(2);
}

function Csv2Table2(props: any) {
  console.log(props.csv)
  // useState([[""]]) 必须使用这种形式，不然无法赋值
  const [csvData, setCsvData] = useState([[""]]);
  const [newCsvData, setNewCsvData] = useState([[""]]);
  useEffect(() => {
    let data = [];
    props.csv
      .trimEnd()
      .split("\n")
      .map((item_row: any, row: any) => {
        const rowdata = item_row.split("\t").map((item_col: any, col: any) => {
          return item_col.trimEnd().trimStart();
        });
        data.push(rowdata);
      });
    setCsvData([...data]);
    setNewCsvData([...data]);
  }, [props.csv]);
  // 这里只监控props.csv就好了
  function handleNewCsvDataUpdate(i, j, value) {
    const newData = newCsvData.map((item_row: any, row: any) => {
      return item_row.map((item_col: any, col: any) => {
        if (row === i && col === j) {
          return value;
        } else {
          return item_col;
        }
      });
    });
    setNewCsvData(newData);
    props.setNewWeightCsv(newData);
    const new_csv = newData
      .map((item_row: any, row: any) => {
        const check_row = item_row
          .map((item_col: any, col: any) => {
            return item_col ? item_col : csvData[row][col];
          })
          .join("\t");
        return check_row;
      })
      .join("\n");
    props.setNewWeightCsv(new_csv);
  }
  return (
    <table className="table-auto text-base border-collapse">
      <caption className="caption-top text-lg font-bold">
        {`${props.user}.${props.work}.${props.weight}.csv`}
      </caption>
      <thead>
        <tr>
          <th
            key={"index"}
            className="text-lg text-center uppercase align-middle font-semibold p-2"
          >
            index
          </th>
          {csvData.slice(0, 1)[0].map((row_num: any, id: any) => {
            return (
              <th
                key={id}
                className="text-lg text-center uppercase align-middle font-semibold p-2"
              >
                {row_num}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody className="">
        {csvData.slice(1).map((item_row: any, row: any) => {
          return (
            <tr key={"row_" + row} className="border border-slate-300">
              <td key={"idx_" + row}>
                <a key={"value_" + row}>{row}</a>
              </td>
              {item_row.map((item_column: any, column: any) => {
                // <></> 空元组也会需要key
                return column == item_row.length - 1 ? (
                  <td
                    key={"value_" + column}
                    className="text-center lining-nums"
                  >
                    <TextInput
                      key={column + "_input"}
                      sizing="md"
                      onChange={(e) => {
                        handleNewCsvDataUpdate(row + 1, column, e.target.value);
                      }}
                      value={newCsvData[row + 1][column]}
                      color={
                        newCsvData[row + 1][column] == csvData[row + 1][column]
                          ? "gray"
                          : newCsvData[row + 1][column] && "info"
                      }
                      // defaultValue={item_column}
                      // defaultValue 和 value 不能同时用
                      placeholder={item_column}
                      addon={item_column}
                    />
                  </td>
                ) : (
                  <td key={"value_" + column}>
                    <a>{item_column}</a>
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export { FormWorkChoose, FormWorkResult, FormWorkNew, FormWeightOptim, FormSinglePointResults };
