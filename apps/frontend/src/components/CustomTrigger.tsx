import {useSidebar} from "@/components/ui/sidebar";
import {Button} from "@/components/ui/button";
import { HamburgerIcon, Menu} from "lucide-react";


const CustomTrigger = () =>  {

    const {toggleSidebar, state} = useSidebar()

    return(
        <Button variant="ghost" size="icon" onClick={toggleSidebar} className="p-3! w-3! h-3! rounded-full! bg-white! focus-visible:ring-0! relative z-50 left-3 top-5 hover:bg-grey-400!">
            <Menu className={state == "collapsed"? "rotate-180" : ""} />
            <span className="sr-only">toggle sidebar</span>
        </Button>
    )
}

export default CustomTrigger