/*
 * @Author       : yf_Ming && yf_Ming@csu.edu.cn
 * @Date         : 2023-09-05 16:50:53
 * @LastEditors  : yf_Ming@hpc_web yf_Ming@csu.edu.cn
 * @LastEditTime : 2023-09-19 01:52:22
 * @FilePath     : /src/WebHub/WebUI/src/components/InputTemplate.tsx
 * Copyright (c) 2023, All Rights Reserved.
 */
import axios from "axios";
import { useEffect, useState } from "react";
import { Label, Select, Tooltip } from "flowbite-react"
import { HiQuestionMarkCircle } from "react-icons/hi"

function LabelInput(props) {
  const [tooltipReady, setTooltipReady] = useState(false);

  useEffect(() => {
    setTooltipReady(true);
  }, []);

  return (
    <div id={props.type + props.id}>
      <div className="flex mb-2 justify-center gap-3 text-base">
        <Label
          color={props.color}
          htmlFor={props.id}
          value={props.id} />
        {props.help && tooltipReady &&
          <Tooltip
            content={props.help} style='auto'>
            <HiQuestionMarkCircle className="w-5 h-5" />
          </Tooltip>}
        {props.help && !tooltipReady &&
          <HiQuestionMarkCircle className="w-5 h-5" />}
      </div>
      <props.func
        sizing="base"
        accept={props.type}
        // defaultValue={props.default}
        ref={props.reference}
        onChange={props.onChange ? props.onChange : () => { }}
        {...props}
      />
    </div>
  )
}


function SelectInput(props) {
  return <div className='w-full'
  >
    <Select
      {...props}
      // ref={Data.taskId}
      onClick={() => {
        axios.get('/api_dft/work_list/' + props.user + '/' + props.work)
          .then((response: any) => {
            props.setWorkList(response.data);
          })
          .catch(function (error: any) {
          });
      }}
    >
      <option key="0">{props.defaultValue}</option>
      {Array.from({ length: props.list.length }, (_, i) => (
        <option key={i}>{props.list[i]}</option>
      ))}
    </Select>
  </div>;
}

export { LabelInput, SelectInput }
