/*
 * @Author       : yf_Ming && yf_Ming@csu.edu.cn
 * @Date         : 2023-09-05 08:58:30
 * @LastEditors  : yf_Ming@hpc_web yf_Ming@csu.edu.cn
 * @LastEditTime : 2023-09-26 13:43:41
 * @FilePath     : /HXWEB/app/WebHub/WebUI/src/components/HistoryTemplate.tsx
 * Copyright (c) 2023, All Rights Reserved.
 */
'use client';

import { Table, Checkbox, Badge } from 'flowbite-react';
import { useEffect, useState } from 'react';
import { HiRefresh } from 'react-icons/hi';
import axios from 'axios';

// Map a derived task status to a flowbite Badge color.
function statusColor(s) {
    switch (s) {
        case 'Success': return 'success';
        case 'Failed': return 'failure';
        case 'Running': return 'info';
        case 'Interrupted': return 'warning';
        case 'Queued': return 'gray';
        default: return 'gray';
    }
}


export default function HistoryTable(props) {
    const [currentRow, setCurrentRow] = useState();
    useEffect(() => {
        setCurrentRow(props.handle)
    }, [props])
    function handleClickRow(work) {
        setCurrentRow(work)
        props.setHandle(work)
        // alert("Choose work:\n" + work)
    }
    return (
        <>
            <Table hoverable className='table-auto bg-gray-500 text-base' >
                <TableHead head_list={props.head_list} handleFresh={props.handleFresh} />
                <Table.Body className="divide-y  ">
                    {props.work_list.map((item, index) => {
                        return <TableRow data={item} id={index}
                            {...props} key={index}
                            row={currentRow} handleRow={handleClickRow}
                        />
                    })}
                </Table.Body>
            </Table>
        </>
    )
}

function TableHead(props) {
    const list = props.head_list
    return <Table.Head>
        <Table.HeadCell className="">
            <HiRefresh className='transition h-5 w-5 hover:rotate-180'
                onClick={props.handleFresh} />
        </Table.HeadCell>
        {list.map((head, index) => {
            return <Table.HeadCell key={index}> {head}</Table.HeadCell>
        })
        }
    </Table.Head>;
}

function TableRow(props) {
    const status=props.data['status']
    const mue=props.data['total_mue']

    return <Table.Row className="bg-white dark:border-gray-700 dark:bg-gray-800" onClick={(e) => {
        props.handleRow(props.data.name)
    }}>
        <Table.Cell key={props.id} className="flex gap-2 items-center">
            <Checkbox checked={props.row == props.data.name} onChange={ (e)=>{}} />
            {props.id + 1}
        </Table.Cell>
        {props.head_list.map((head, index) => {
            return (
                head == 'Status' ?
                    (<Table.Cell key={props.id + "_status"} className='flex'>
                        {status ? <Badge color={statusColor(status)}> {status}</Badge> :
                            <Badge color="gray"> unkown</Badge>}
                    </Table.Cell >) :
                    (head == 'Total_MUE' ?
                        (<Table.Cell key={props.id + "_mue"} className='flex'>
                        {mue ? <Badge color="success"> {mue}</Badge> :
                            <Badge color="gray"> unkown</Badge>}
                    </Table.Cell>) :
                        props.data[head] &&
                        <Table.Cell key={index} className='antialiased' >
                            {props.data[head]}
                        </Table.Cell>)
            )
        })}
    </Table.Row>;
}
